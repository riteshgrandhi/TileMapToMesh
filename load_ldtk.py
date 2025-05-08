# -*- coding: utf-8 -*-
bl_info = {
    "name": "Load LDtk Tilemap (.ldtk)",
    "author": "Gemini Code Assist",
    "version": (1, 0),
    "blender": (3, 0, 0),  # Minimum Blender version
    "location": "File > Import > LDtk Tilemap (.ldtk)",
    "description": "Loads a tilemap from an LDtk file (.ldtk)",
    "warning": "",
    "doc_url": "",
    "category": "Import-Export",
}

import bpy
import bmesh
import os
import json
from bpy_extras.io_utils import ImportHelper
from mathutils import Vector

# --- Helper Functions ---

def get_absolute_path(filepath, rel_path):
    """Calculates the absolute path for a resource relative to the LDtk file."""
    if not rel_path:
        return None
    if os.path.isabs(rel_path):
        return rel_path
    ldtk_dir = os.path.dirname(filepath)
    return os.path.normpath(os.path.join(ldtk_dir, rel_path))

def load_texture(image_path, operator):
    """Loads a texture image into Blender or returns existing one."""
    if not image_path or not os.path.exists(image_path):
        operator.report({'WARNING'}, f"Texture image not found: {image_path}")
        return None

    img_name = os.path.basename(image_path)
    img = bpy.data.images.get(img_name)
    if img is None:
        try:
            img = bpy.data.images.load(image_path, check_existing=True)
            operator.report({'INFO'}, f"Loaded texture: {img_name}")
        except Exception as e:
            operator.report({'ERROR'}, f"Failed to load texture {img_name}: {e}")
            return None
    else:
        operator.report({'INFO'}, f"Using existing texture: {img_name}")
    return img

def create_tile_material(mat_name, image, operator):
    """Creates a Blender material for a tileset image."""
    if mat_name in bpy.data.materials:
        operator.report({'INFO'}, f"Using existing material: {mat_name}")
        return bpy.data.materials[mat_name]

    mat = bpy.data.materials.new(name=mat_name)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get('Principled BSDF')
    if bsdf:
        mat.node_tree.nodes.remove(bsdf)

    nodes = mat.node_tree.nodes
    links = mat.node_tree.links

    output_node = nodes.get('Material Output')
    tex_image_node = nodes.new('ShaderNodeTexImage')
    emission_node = nodes.new('ShaderNodeEmission')
    transparent_node = nodes.new('ShaderNodeBsdfTransparent')
    mix_shader_node = nodes.new('ShaderNodeMixShader')

    tex_image_node.image = image
    tex_image_node.interpolation = 'Closest' # Pixel art friendly

    # Position nodes for clarity (optional)
    tex_image_node.location = (-600, 300)
    emission_node.location = (-300, 400)
    transparent_node.location = (-300, 100)
    mix_shader_node.location = (0, 300)
    output_node.location = (300, 300)

    # Link nodes
    links.new(tex_image_node.outputs['Color'], emission_node.inputs['Color'])
    links.new(tex_image_node.outputs['Alpha'], mix_shader_node.inputs['Fac'])
    links.new(emission_node.outputs['Emission'], mix_shader_node.inputs[2]) # Shader 2 input
    links.new(transparent_node.outputs['BSDF'], mix_shader_node.inputs[1]) # Shader 1 input
    links.new(mix_shader_node.outputs['Shader'], output_node.inputs['Surface'])

    # Set blend mode for transparency
    mat.blend_method = 'BLEND'
    # mat.shadow_method = 'NONE' # Tiles shouldn't cast shadows usually

    operator.report({'INFO'}, f"Created material: {mat_name}")
    return mat

# --- Property Group for Layer Instance Selection (within a level) ---
class LDtkLayerInstanceImportProperties(bpy.types.PropertyGroup):
    name: bpy.props.StringProperty( # Layer instance identifier or type
        name="Layer Instance Name",
        description="Identifier of the layer instance or its type/definition"
    )
    instance_iid: bpy.props.StringProperty( # LDtk layer instance IID
        name="Instance IID",
        description="Unique IID of this layer instance in the LDtk project"
    )
    layer_def_uid: bpy.props.StringProperty( # Original Layer Definition UID
        name="Layer Definition UID",
        description="UID of the original layer definition"
    )
    import_layer: bpy.props.BoolProperty(
        name="Import",
        description="Import this layer instance",
        default=True
    )

# --- Property Group for Level Selection ---
class LDtkLevelImportProperties(bpy.types.PropertyGroup):
    name: bpy.props.StringProperty( # Level identifier
        name="Level Name",
        description="Identifier of the level"
    )
    level_iid: bpy.props.StringProperty( # LDtk level IID
        name="Level IID",
        description="Original IID of the level in the LDtk project"
    )
    import_level: bpy.props.BoolProperty(
        name="Import",
        description="Import this level",
        default=True
    )
    layer_instances: bpy.props.CollectionProperty(
        type=LDtkLayerInstanceImportProperties,
        name="Layer Instances in this Level"
    )
    # For UI state, to show/hide layer instances
    show_layers: bpy.props.BoolProperty(
        name="Show Layers",
        description="Expand to show layer instances for this level",
        default=True
    )

# --- Helper Operators for Layer Selection ---
class LDtkSelectionHelperBase(bpy.types.Operator):
    """Base class for selection helper operators."""
    bl_idname = "tilemaputil.select_helper_base"
    bl_label = "Selection Helper Base"
    bl_options = {'INTERNAL'}

    def get_main_operator(self, context):
        if hasattr(context, 'space_data') and hasattr(context.space_data, 'operator'):
            op = context.space_data.operator
            if op and op.bl_idname == UTIL_OP_LoadLdtk.bl_idname:
                return op
        # Fallback for direct calls if needed, though less common for INTERNAL ops
        if context.active_operator and context.active_operator.bl_idname == UTIL_OP_LoadLdtk.bl_idname:
            return context.active_operator
        return None

    def invoke(self, context, event):
        main_op = self.get_main_operator(context)
        if not main_op:
            self.report({'WARNING'}, "Main LDtk import operator not found.")
            return {'CANCELLED'}
        self.execute(context)
        for area in context.screen.areas:
            if area.type == 'FILE_BROWSER':
                area.tag_redraw()
                break
        return {'FINISHED'}

# --- Operator Class ---

class UTIL_OP_LoadLdtk(bpy.types.Operator, ImportHelper):
    """Loads a tilemap from an LDtk file (.ldtk)"""
    bl_idname = "tilemaputil.ldtk_loader"
    bl_label = "Load LDtk Tilemap (.ldtk)"
    bl_options = {'REGISTER', 'UNDO'}

    # Filter for .ldtk files
    filter_glob: bpy.props.StringProperty(
        default="*.ldtk",
        options={'HIDDEN'},
        maxlen=255,  # Max path length
    )

    # --- Operator Properties ---
    import_scale: bpy.props.FloatProperty(
        name="Import Scale",
        description="Scale the imported tilemap object",
        default=1.0,
        min=0.01,
    )

    layer_separation: bpy.props.FloatProperty(
        name="Layer Separation (Z)",
        description="Distance between layers along the Z-axis",
        default=0.1,
        min=0.0,
    )

    levels_to_import: bpy.props.CollectionProperty(
        type=LDtkLevelImportProperties,
        name="Levels to Import"
    )
    data_parsed_for_ui: bpy.props.BoolProperty(
        default=False,
        options={'HIDDEN'},
        description="Internal: Whether levels and layers have been parsed from the current file for UI"
    )
    processed_filepath: bpy.props.StringProperty(
        options={'HIDDEN'},
        description="Internal: Path for which layers are currently loaded/processed"
    )

    def _populate_levels_and_layers_for_import(self, main_ldtk_json_data, base_ldtk_filepath, context_prefix=""):
        """
        Populates `self.levels_to_import` based on the provided LDtk data.
        Sets `self.data_parsed_for_ui` accordingly.
        """
        self.levels_to_import.clear()
        self.data_parsed_for_ui = False # Assume failure until success

        if not main_ldtk_json_data:
            self.report({'WARNING'}, f"{context_prefix}No main LDtk data provided for populating options.")
            return

        if 'levels' in main_ldtk_json_data and main_ldtk_json_data['levels']:
            for level_data_ref in main_ldtk_json_data['levels']: # level_data_ref is from main_ldtk_json_data
                level_item = self.levels_to_import.add()
                # Identifier and IID always come from the main project file's level entry
                level_item.name = level_data_ref.get('identifier', f"Level_IID_{level_data_ref.get('iid', 'UnknownIID')}")
                level_item.level_iid = level_data_ref.get('iid', '')
                level_item.import_level = True # Default to import
                level_item.show_layers = False # Default to collapsed for UI, harmless for execute

                # Determine the source of layer instances (main file or external file)
                layer_instances_source_data = level_data_ref # Default to data from the main project file
                external_rel_path = level_data_ref.get('externalRelPath')

                if external_rel_path:
                    abs_ext_level_path = get_absolute_path(base_ldtk_filepath, external_rel_path)
                    if abs_ext_level_path and os.path.exists(abs_ext_level_path):
                        try:
                            with open(abs_ext_level_path, 'r', encoding='utf-8') as ext_f:
                                external_level_json = json.load(ext_f)
                            layer_instances_source_data = external_level_json # Use this for layerInstances
                            self.report({'INFO'}, f"{context_prefix}Found external level data for '{level_item.name}' at '{external_rel_path}'")
                        except Exception as e_ext:
                            self.report({'WARNING'}, f"{context_prefix}Error parsing external level file '{external_rel_path}' for level '{level_item.name}': {e_ext}")
                            # If external parsing fails, layer_instances_source_data remains level_data_ref
                    else:
                        self.report({'WARNING'}, f"{context_prefix}External level file not found for '{level_item.name}': '{external_rel_path}' (resolved: {abs_ext_level_path})")
                        # If external file not found, layer_instances_source_data remains level_data_ref

                level_item.layer_instances.clear()
                for layer_instance_data in layer_instances_source_data.get('layerInstances', []):
                    layer_inst_item = level_item.layer_instances.add()
                    layer_inst_item.name = layer_instance_data.get('__identifier', f"Type_{layer_instance_data.get('__type', 'UnknownType')}_DefUID_{layer_instance_data.get('layerDefUid','UnknownDef')}")
                    layer_inst_item.instance_iid = layer_instance_data.get('iid', '') # Layer instance IID
                    layer_inst_item.layer_def_uid = str(layer_instance_data.get('layerDefUid', ''))
                    layer_inst_item.import_layer = True # Default to import
            self.data_parsed_for_ui = True
        else:
            # self.data_parsed_for_ui remains False
            self.report({'INFO'}, f"{context_prefix}No levels found in the provided LDtk data.")

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False

        layout.prop(self, "import_scale")
        layout.prop(self, "layer_separation")

        # Logic to update layer list if filepath changes
        if self.filepath != self.processed_filepath:
            self.levels_to_import.clear() # Clear before attempting to parse
            self.data_parsed_for_ui = False # Reset flag

            if self.filepath and os.path.exists(self.filepath):
                try:
                    with open(self.filepath, 'r', encoding='utf-8') as f:
                        ldtk_data_for_ui = json.load(f)
                    # Call the new helper method to populate levels_to_import
                    self._populate_levels_and_layers_for_import(ldtk_data_for_ui, self.filepath, context_prefix="UI: ")
                except Exception as e:
                    self.report({'WARNING'}, f"Error parsing LDtk for UI: {e}")
                    # self.data_parsed_for_ui remains False, levels_to_import is already cleared
            
            self.processed_filepath = self.filepath # Mark as processed for this path

        # Display layer selection UI
        if self.data_parsed_for_ui and self.levels_to_import:
            box = layout.box()
            box.label(text="Levels and Layer Instances to Import:")

            for level_item in self.levels_to_import:
                level_box = box.box() # Box per level for visual grouping
                header_row = level_box.row(align=True)
                icon = 'TRIA_DOWN' if level_item.show_layers else 'TRIA_RIGHT'
                header_row.prop(level_item, "show_layers", text="", icon=icon, emboss=False)
                header_row.prop(level_item, "import_level", text="")
                header_row.label(text=level_item.name)

                if level_item.show_layers:
                    layers_box = level_box.box()
                    for layer_instance_item in level_item.layer_instances:
                        layer_row = layers_box.row(align=True)
                        layer_row.prop(layer_instance_item, "import_layer", text="")
                        layer_row.label(text=f"  {layer_instance_item.name}") # Indent layer name

        elif self.filepath and os.path.exists(self.filepath) and not self.data_parsed_for_ui:
            layout.label(text=f"No levels/layers found or error parsing: {os.path.basename(self.filepath)}")
        elif self.filepath and not os.path.exists(self.filepath):
            layout.label(text="File not found. Please select a valid LDtk file.")

    def execute(self, context):
        filepath = self.filepath
        scale = self.import_scale
        layer_sep = self.layer_separation

        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                ldtk_data = json.load(f)
        except Exception as e:
            self.report({'ERROR'}, f"Failed to read or parse LDtk file: {e}")
            return {'CANCELLED'}

        self.report({'INFO'}, f"Loading LDtk file: {filepath}")

        # Ensure levels_to_import is populated if UI didn't run,
        # or if the filepath changed since UI was last drawn.
        # The ldtk_data loaded above is used for this.
        if not self.data_parsed_for_ui or self.processed_filepath != self.filepath:
            self.report({'INFO'}, "Populating import options from LDtk data for execution.")
            # Use the ldtk_data already loaded for the import process
            self._populate_levels_and_layers_for_import(ldtk_data, self.filepath, context_prefix="Execute: ")
            if self.data_parsed_for_ui: # Only update processed_filepath if parsing was successful
                self.processed_filepath = self.filepath

        if not self.data_parsed_for_ui: # Check after attempting to populate
            self.report({'ERROR'}, f"Could not determine levels/layers to import from: {filepath}. Aborting.")
            return {'CANCELLED'}
        
        # If _populate_levels_and_layers_for_import found no levels in the data structure.
        if not self.levels_to_import:
            self.report({'INFO'}, "No levels found in LDtk data structure. Nothing to import.")
            return {'FINISHED'}

        # --- Data Storage ---
        tileset_defs = {ts['uid']: ts for ts in ldtk_data['defs']['tilesets']}
        loaded_textures = {} # uid: bpy.data.Image
        created_materials = {} # uid: bpy.data.Material
        layer_defs = {layer['uid']: layer for layer in ldtk_data['defs']['layers']}
        int_grid_value_tiles = {} # layer_uid: {value: tile_info}

        # --- Pre-process Tilesets and Materials ---
        self.report({'INFO'}, "Processing tilesets...")
        for uid, ts_def in tileset_defs.items():
            # Handle embedded atlas (like LDtk internal icons)
            if ts_def.get('embedAtlas') == 'LdtkIcons':
                 # Skip internal icons for now, or handle specifically if needed
                 self.report({'INFO'}, f"Skipping internal LDtk icons tileset: {ts_def['identifier']}")
                 continue

            rel_path = ts_def.get('relPath')
            if not rel_path:
                self.report({'WARNING'}, f"Tileset '{ts_def['identifier']}' has no relPath, skipping.")
                continue

            abs_path = get_absolute_path(filepath, rel_path)
            if not abs_path:
                 self.report({'WARNING'}, f"Could not resolve path for tileset '{ts_def['identifier']}' ({rel_path}), skipping.")
                 continue

            image = load_texture(abs_path, self)
            if not image:
                continue # Error reported in load_texture

            loaded_textures[uid] = image
            mat_name = f"mat_{ts_def['identifier']}"
            material = create_tile_material(mat_name, image, self)
            created_materials[uid] = material

        # --- Pre-process IntGrid Visuals ---
        self.report({'INFO'}, "Processing IntGrid value definitions...")
        for uid, layer_def in layer_defs.items():
            if layer_def['__type'] == 'IntGrid' and layer_def.get('tilesetDefUid') is not None:
                value_map = {}
                for val_def in layer_def.get('intGridValues', []):
                    if val_def.get('tile'): # Check if a tile is associated
                        value_map[val_def['value']] = val_def['tile']
                if value_map:
                    int_grid_value_tiles[uid] = value_map


        # --- Process Levels ---
        self.report({'INFO'}, "Processing levels...")
        level_count = len(ldtk_data.get('levels', []))

        for level_idx, level_data_ref in enumerate(ldtk_data.get('levels', [])): # level_data_ref is from the main LDtk file
            z_offset = 0.0
            level_iid = level_data_ref.get('iid')
            # Find this level in our selection list
            level_import_settings = next((lvl for lvl in self.levels_to_import if lvl.level_iid == level_iid), None)

            if not level_import_settings or not level_import_settings.import_level:
                self.report({'INFO'}, f"Skipping level '{level_data_ref.get('identifier', f'IID_{level_iid}')}' as it's not selected for import.")
                continue

            # Use the identifier from the main project file for naming Blender objects
            level_name = level_data_ref.get('identifier', f'Level_{level_idx}')
            self.report({'INFO'}, f"Processing {level_name} ({level_idx + 1}/{level_count})")

            # Determine the actual level data to use (from main file or external file)
            actual_level_data = level_data_ref # Default to data from the main project file
            external_rel_path = level_data_ref.get('externalRelPath')

            if external_rel_path:
                abs_external_level_path = get_absolute_path(filepath, external_rel_path)
                if abs_external_level_path and os.path.exists(abs_external_level_path):
                    try:
                        with open(abs_external_level_path, 'r', encoding='utf-8') as ext_f:
                            actual_level_data = json.load(ext_f) # Override with external data
                        self.report({'INFO'}, f"Successfully loaded external level data for '{level_name}' from: {abs_external_level_path}")
                    except Exception as e_ext_load:
                        self.report({'ERROR'}, f"Failed to load or parse external level file '{abs_external_level_path}' for level '{level_name}': {e_ext_load}. Skipping this level.")
                        continue
                else:
                    self.report({'ERROR'}, f"External level file not found for level '{level_name}': '{abs_external_level_path}' (from relPath: '{external_rel_path}'). Skipping this level.")
                    continue

            # Get world coordinates and layer instances from the actual_level_data
            level_origin_x = actual_level_data.get('worldX', 0)
            level_origin_y = actual_level_data.get('worldY', 0) # LDtk Y is down

            # Create a dictionary for quick lookup of layer instance import settings for this level
            current_level_layer_instance_settings = {
                li.instance_iid: li for li in level_import_settings.layer_instances
            }

            # Create a collection for the level, using the name from the main project file's reference
            level_collection = bpy.data.collections.new(level_name)
            context.scene.collection.children.link(level_collection)

            layer_instances = actual_level_data.get('layerInstances', [])
            if not layer_instances:
                continue

            # Sort layers based on LDtk's top-to-bottom order (visual back to front)
            # LDtk layers are listed visually back-to-front, so reverse for Blender Z order

            for layer_instance in layer_instances:
                layer_instance_iid = layer_instance.get('iid')
                layer_instance_import_settings = current_level_layer_instance_settings.get(layer_instance_iid)

                if not layer_instance_import_settings or not layer_instance_import_settings.import_layer:
                    self.report({'INFO'}, f"Skipping layer instance '{layer_instance.get('__identifier', f'IID_{layer_instance_iid}')}' in level '{level_name}' as it's not selected for import.")
                    continue

                layer_def_uid = layer_instance['layerDefUid']
                layer_definition = layer_defs.get(layer_def_uid)
                if not layer_definition:
                    self.report({'WARNING'}, f"Layer definition UID {layer_def_uid} not found, skipping layer.")
                    continue
                

                layer_identifier = layer_instance.get('__identifier', f'Layer_{layer_def_uid}')
                layer_type = layer_instance['__type']
                grid_size = layer_instance['__gridSize']
                layer_c_wid = layer_instance['__cWid']
                layer_c_hei = layer_instance['__cHei']
                layer_visible = layer_instance.get('visible', True)

                if not layer_visible:
                    self.report({'INFO'}, f"Skipping hidden layer: {layer_identifier}")
                    continue

                mesh = None
                bm = None
                obj = None
                tiles_to_process = [] # List of tuples: (px, src, f, tileset_uid)
                material_indices = {} # tileset_uid: material_index
                current_material_index = 0
                layer_tileset_uid = layer_instance.get('__tilesetDefUid') # Used by Tiles, AutoLayer, sometimes IntGrid

                # --- Gather Tile Data ---
                if layer_type in ["Tiles", "AutoLayer"]: # Fixed: Was empty list
                    if layer_tileset_uid is None:
                        self.report({'WARNING'}, f"Layer '{layer_identifier}' of type '{layer_type}' has no tileset UID, skipping.")
                        continue
                    if layer_tileset_uid not in created_materials:
                         self.report({'WARNING'}, f"Material for tileset UID {layer_tileset_uid} not found/created for layer '{layer_identifier}', skipping.")
                         continue

                    tiles = layer_instance.get('gridTiles', []) + layer_instance.get('autoLayerTiles', [])
                    for tile in tiles:
                        # px: [x, y], src: [x, y], f: flip bits, t: tileId (optional)
                        tiles_to_process.append((tile['px'], tile['src'], tile['f'], layer_tileset_uid))

                elif layer_type == "IntGrid":
                    if layer_tileset_uid is None or layer_def_uid not in int_grid_value_tiles:
                        self.report({'INFO'}, f"IntGrid layer '{layer_identifier}' has no visual tiles defined, skipping mesh generation.")
                        continue # Skip if no visual representation defined
                    if layer_tileset_uid not in created_materials:
                         self.report({'WARNING'}, f"Material for tileset UID {layer_tileset_uid} not found/created for IntGrid layer '{layer_identifier}', skipping.")
                         continue

                    # value_tile_map = int_grid_value_tiles[layer_def_uid]
                    int_grid_csv = layer_instance.get('intGridCsv', [])
                    if not int_grid_csv:
                        continue

                    tiles = layer_instance.get('gridTiles', []) + layer_instance.get('autoLayerTiles', [])
                    for tile in tiles:
                        int_grid_index = int((tile["px"][0]/grid_size) + (tile["px"][1]/grid_size * layer_c_wid))
                        if int_grid_csv[int_grid_index] != 0:
                            # px: [x, y], src: [x, y], f: flip bits, t: tileId (optional)
                            tiles_to_process.append((tile['px'], tile['src'], tile['f'], layer_tileset_uid))

                elif layer_type == "Entities":
                    # Basic entity import as planes (optional, can be expanded)
                    # For now, just report and skip mesh generation for entities layer itself
                    self.report({'INFO'}, f"Skipping mesh generation for Entities layer: {layer_identifier}. Entities might be handled separately.")
                    continue
                else:
                    self.report({'WARNING'}, f"Unsupported layer type '{layer_type}' for layer '{layer_identifier}', skipping.")
                    continue

                if not tiles_to_process:
                    self.report({'INFO'}, f"No visual tiles found for layer '{layer_identifier}'.")
                    continue

                # --- Create Mesh and Object ---
                mesh_name = f"{level_name}_{layer_identifier}"
                mesh = bpy.data.meshes.new(mesh_name)
                obj = bpy.data.objects.new(mesh_name, mesh)
                obj.location = (0, 0, z_offset)
                level_collection.objects.link(obj) # Link object to the level's collection

                bm = bmesh.new()
                # verts_dict = {} # Store vertices to reuse: {(x, y): vert_index}

                # --- Process Tiles and Build Mesh ---
                self.report({'INFO'}, f"Building mesh for layer: {layer_identifier}...")
                for px, src, flip_flags, ts_uid in tiles_to_process:
                    if ts_uid not in created_materials:
                        continue # Skip if material wasn't created

                    # Get material index for this tileset
                    if ts_uid not in material_indices:
                        mat = created_materials[ts_uid]
                        obj.data.materials.append(mat)
                        material_indices[ts_uid] = current_material_index
                        current_material_index += 1
                    mat_idx = material_indices[ts_uid]

                    # Get tileset definition for dimensions
                    ts_def = tileset_defs.get(ts_uid)
                    if not ts_def: continue
                    tile_w = ts_def.get('tileGridSize', grid_size) # Use layer grid size as fallback
                    tile_h = tile_w # Assume square tiles if only one dim given
                    tex_image = loaded_textures.get(ts_uid)
                    if not tex_image: continue
                    img_w, img_h = tex_image.size

                    # Calculate vertex coordinates in Blender space (relative to object origin)
                    # LDtk px is top-left corner, Y-down
                    # Blender object space is typically Y-up or Z-up, origin at center or corner
                    # Let's map LDtk X to Blender X, LDtk Y to Blender -Y, origin at LDtk's top-left
                    v1_coord = ((px[0] + level_origin_x) * scale / grid_size, -(px[1] + level_origin_y) * scale / grid_size, 0)
                    v2_coord = ((px[0] + tile_w + level_origin_x) * scale / grid_size, -(px[1] + level_origin_y) * scale / grid_size, 0)
                    v3_coord = ((px[0] + tile_w + level_origin_x) * scale / grid_size, -(px[1] + tile_h + level_origin_y) * scale / grid_size, 0)
                    v4_coord = ((px[0] + level_origin_x) * scale / grid_size, -(px[1] + tile_h + level_origin_y) * scale / grid_size, 0)

                    coords = [v1_coord, v2_coord, v3_coord, v4_coord]
                    verts = []

                    # Reuse or create vertices
                    for coord in coords:
                        # Round coordinates slightly to help vertex merging
                        # key = tuple(round(c, 5) for c in coord)
                        # if key in verts_dict:
                        #     bm.verts.ensure_lookup_table()
                        #     verts.append(bm.verts[verts_dict[key]])
                        # else:
                        new_vert = bm.verts.new(coord)
                        verts.append(new_vert)
                        # verts_dict[key] = new_vert.index

                    # Create face
                    try:
                        face = bm.faces.new(verts)
                        face.material_index = mat_idx
                        face.smooth = False # Keep pixel look sharp

                        # --- UV Mapping ---
                        uv_layer = bm.loops.layers.uv.verify() # Get or create UV layer

                        # Calculate UV coordinates (normalized 0-1)
                        u_min = src[0] / img_w
                        u_max = (src[0] + tile_w) / img_w
                        v_min = 1.0 - (src[1] + tile_h) / img_h # Flip V for Blender
                        v_max = 1.0 - src[1] / img_h

                        uvs = [
                            Vector((u_min, v_max)), # Top-left
                            Vector((u_max, v_max)), # Top-right
                            Vector((u_max, v_min)), # Bottom-right
                            Vector((u_min, v_min)), # Bottom-left
                        ]

                        # Handle flipping (f: 0=None, 1=X, 2=Y, 3=XY)
                        flip_x = (flip_flags & 1) != 0
                        flip_y = (flip_flags & 2) != 0
                        px

                        if flip_x:
                            uvs[0][0], uvs[1][0] = uvs[1][0], uvs[0][0]
                            uvs[3][0], uvs[2][0] = uvs[2][0], uvs[3][0]
                        if flip_y:
                            uvs[0][1], uvs[3][1] = uvs[3][1], uvs[0][1]
                            uvs[1][1], uvs[2][1] = uvs[2][1], uvs[1][1]

                        # Assign UVs to face loops (order matters: BL, BR, TR, TL for default quad)
                        # The order depends on how bm.faces.new orders the loops. Let's check.
                        # Assuming standard counter-clockwise order from bottom-left for bm.faces.new(verts)
                        # verts = [v1(TL), v2(TR), v3(BR), v4(BL)] -> face loops might be BL, BR, TR, TL
                        # Let's assign based on vertex order provided:
                        # face.loops[0][uv_layer].uv = uvs[0] # Corresponds to v1 (TL)
                        # face.loops[1][uv_layer].uv = uvs[1] # Corresponds to v2 (TR)
                        # face.loops[2][uv_layer].uv = uvs[2] # Corresponds to v3 (BR)
                        # face.loops[3][uv_layer].uv = uvs[3] # Corresponds to v4 (BL)
                        for i, loop in enumerate(face.loops):
                            # uv = (Vector((tile_x, tile_y)) + LOOP_OFFSET_DICT[i]) * Vector((tiledata.tile_width, - tiledata.tile_height)) + Vector((0, 1))
                            loop[uv_layer].uv = uvs[i]

                    except ValueError as ve:
                        # Handle potential errors like duplicate vertices in a face
                        self.report({'WARNING'}, f"Could not create face for tile at {px} in layer '{layer_identifier}': {ve}. Skipping tile.")
                        # Clean up potentially invalid verts if necessary, though bmesh usually handles this
                        pass
                    except Exception as ex:
                         self.report({'ERROR'}, f"Unexpected error creating face for tile at {px} in layer '{layer_identifier}': {ex}. Skipping tile.")
                         pass


                # --- Finalize Mesh ---
                if bm and obj:
                    # Remove duplicate vertices
                    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=0.0001)
                    bm.to_mesh(mesh)
                    bm.free()
                    mesh.update()
                    self.report({'INFO'}, f"Finished mesh for layer: {layer_identifier}")
                elif bm:
                    bm.free() # Free bmesh even if object creation failed

                # Increment Z offset for the next layer in this level
                z_offset -= layer_sep

        self.report({'INFO'}, "LDtk import finished.")
        return {'FINISHED'}

# --- Registration ---

def menu_func_import(self, context):
    self.layout.operator(UTIL_OP_LoadLdtk.bl_idname, text=UTIL_OP_LoadLdtk.bl_label)

def register():
    bpy.utils.register_class(LDtkSelectionHelperBase)
    bpy.utils.register_class(LDtkLayerInstanceImportProperties)
    bpy.utils.register_class(LDtkLevelImportProperties)
    bpy.utils.register_class(UTIL_OP_LoadLdtk)
    bpy.types.TOPBAR_MT_file_import.append(menu_func_import)

def unregister():
    bpy.utils.unregister_class(UTIL_OP_LoadLdtk)
    bpy.utils.unregister_class(LDtkLevelImportProperties)
    bpy.utils.unregister_class(LDtkLayerInstanceImportProperties)
    bpy.utils.unregister_class(LDtkSelectionHelperBase)
    bpy.types.TOPBAR_MT_file_import.remove(menu_func_import)

if __name__ == "__main__":
    # Unregister previous version if exists before registering
    try:
        unregister()
    except Exception:
        pass
    register()
