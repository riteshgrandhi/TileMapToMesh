import os
import bpy
import pytmx
import bmesh
from bpy_extras.io_utils import ImportHelper
from bmesh.types import BMesh, BMFace
from bpy.types import Image
from mathutils import Vector

LOOP_OFFSET_DICT = {
    0: Vector((0, 0)),
    1: Vector((0, 1)),
    2: Vector((1, 1)),
    3: Vector((1, 0))
}

class UTIL_OP_LoadTilemap(bpy.types.Operator, ImportHelper):
    bl_idname = "tilemaputil.tilemap_load"
    bl_label = "Load Tilemap"
    bl_description = "load a tilemap"

    # For some reason this full list doesn't really work,
    # reordered the list to prioritize common file types
    # filter_ext = "*" + ";*".join(bpy.path.extensions_image.sort())

    filter_glob: bpy.props.StringProperty(
        default="*.tmx",
        options={'HIDDEN'},
    )

    def execute(self, context):
        tilemap = UTIL_OP_LoadTilemap.load_tilemap_file(context, self.filepath)

        tileset, img = self.load_texture_image(tilemap, self.filepath)

        mat = self.create_material(tilemap, img)
        
        obj = self.create_mesh_object(tilemap, tileset, img)

        # Assign material to object
        if obj.data.materials:
            obj.data.materials[0] = mat
        else:
            obj.data.materials.append(mat)

        bpy.context.view_layer.objects.active = obj
        obj.select_set(True)

        return {'FINISHED'}
    
    @staticmethod
    def load_tilemap_file(context, filepath):
        try:
            return pytmx.TiledMap(filepath)
        except FileNotFoundError:
            print(f"Error: File not found at {filepath}")


    def load_texture_image(self, tilemap: pytmx.TiledMap, filepath):
        # Get the texture path
        tileset: pytmx.TiledTileset = tilemap.tilesets[0]
        texture_path = bpy.path.abspath(os.path.join(os.path.dirname(filepath), tileset.source))
        return tileset, bpy.data.images.load(texture_path)

    
    def create_material(self, tilemap, img):
        if tilemap.tilesets:
            # Create material
            material_name = "TilemapMaterial"
            material = bpy.data.materials.new(name=material_name)
            material.use_nodes = True

            # Create texture and emission nodes
            output_node = material.node_tree.nodes.get("Material Output")
            if output_node is None:
                output_node = material.node_tree.nodes.new(type='ShaderNodeOutputMaterial')
            
            for node in material.node_tree.nodes:
                if node.name != "Material Output":
                    material.node_tree.nodes.remove(node)

            emission_node = material.node_tree.nodes.new(type='ShaderNodeEmission')
            transparent_node = material.node_tree.nodes.new(type='ShaderNodeBsdfTransparent')
            mix_shader_node = material.node_tree.nodes.new(type='ShaderNodeMixShader')
            texture_node = material.node_tree.nodes.new("ShaderNodeTexImage")
            invert_node = material.node_tree.nodes.new(type="ShaderNodeInvert")

            texture_node.image = img
            texture_node.interpolation = 'Closest' #pixel art filtering

            # Link nodes
            material.node_tree.links.new(invert_node.inputs["Color"], texture_node.outputs["Alpha"])
            material.node_tree.links.new(emission_node.inputs["Color"], texture_node.outputs["Color"])
            material.node_tree.links.new(mix_shader_node.inputs[0], invert_node.outputs["Color"])
            material.node_tree.links.new(mix_shader_node.inputs[1], emission_node.outputs["Emission"])
            material.node_tree.links.new(mix_shader_node.inputs[2], transparent_node.outputs["BSDF"])
            material.node_tree.links.new(output_node.inputs["Surface"], mix_shader_node.outputs["Shader"])

            return material

    
    def create_mesh_object(self, tilemap: pytmx.TiledMap, tileset: pytmx.TiledTileset, image: Image, tile_size=1):
        try: 
            bm = bmesh.new()

            verts_map = {}  # Store vertices by their (x, y) coordinates

            tile_width = tileset.tilewidth / image.size[0]
            tile_height = tileset.tileheight / image.size[1]
            columns = image.size[0] // tileset.tilewidth

            uv_layer = bm.loops.layers.uv.verify()

            for layer in tilemap.visible_layers:
                if isinstance(layer, pytmx.TiledTileLayer):
                    for x, y, gid in layer:
                        if gid:  # gid is 0 if no tile
                            verts = [self.get_or_create_vert(tile_size, bm, verts_map, Vector((x, y)) + LOOP_OFFSET_DICT[i]) for i in range(4)]
                            # face_map.setdefault((x, -y), bm.faces.new(verts))
                            face = bm.faces.new(verts)

                            local_gid = tilemap.tiledgidmap.get(gid) - tileset.firstgid
                            tile_x = local_gid % columns
                            tile_y = local_gid // columns
                            self.apply_uv_to_face(face, uv_layer, tile_x, tile_y, tile_width, tile_height)

            mesh = bpy.data.meshes.new("TilemapMesh")
            bm.to_mesh(mesh)
            bm.free()

            obj = bpy.data.objects.new("Tilemap", mesh)
            bpy.context.collection.objects.link(obj)

            return obj
        except Exception as e:
            print(f"An error occurred: {e}")

    def get_or_create_vert(self, tile_size, bm: BMesh, verts_map, v: Vector):
        x, y = v
        return verts_map.get((x, -y)) or verts_map.setdefault((x, -y), bm.verts.new((x * tile_size, -y * tile_size, 0)))

    def apply_uv_to_face(self, face: BMFace, uv_layer, tile_x: int, tile_y: int, tile_width: float, tile_height: float):
        for i, loop in enumerate(face.loops):
            uv = (Vector((tile_x, tile_y)) + LOOP_OFFSET_DICT[i]) * Vector((tile_width, - tile_height)) + Vector((0, 1))
            loop[uv_layer].uv = uv


classes = (
    UTIL_OP_LoadTilemap,
)


def register():
    for cl in classes:
        bpy.utils.register_class(cl)


def unregister():
    for cl in classes:
        bpy.utils.unregister_class(cl)


if __name__ == '__main__':
    register()