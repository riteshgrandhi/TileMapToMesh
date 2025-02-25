from dataclasses import dataclass, field
import os
import bpy
import pytmx
import bmesh
from bpy_extras.io_utils import ImportHelper
from bmesh.types import BMesh, BMFace
from bpy.types import Image, Material
from mathutils import Vector

LOOP_OFFSET_DICT = {
    0: Vector((0, 0)),
    1: Vector((0, 1)),
    2: Vector((1, 1)),
    3: Vector((1, 0))
}

@dataclass
class TileData:
    material: Material
    tileset: pytmx.TiledTileset
    image: Image
    tile_width: float = field(init=False)
    tile_height: float = field(init=False)
    rows: int = field(init=False)
    columns: int = field(init=False)

    def __post_init__(self):
        self.tile_width = self.tileset.tilewidth / self.image.size[0]
        self.tile_height = self.tileset.tileheight / self.image.size[1]
        self.columns = self.image.size[0] // self.tileset.tilewidth
        self.rows = self.image.size[1] // self.tileset.tileheight


class UTIL_OP_LoadTilemap(bpy.types.Operator, ImportHelper):
    bl_idname = "tilemaputil.tilemap_load"
    bl_label = "Load Tilemap"
    bl_description = "load a tilemap"

    filter_glob: bpy.props.StringProperty(
        default="*.tmx",
        options={'HIDDEN'},
    )

    gid_to_tiledata_dict: dict[int, TileData] = {}

    tileset_to_tiledata_dict: dict[pytmx.TiledTileset, TileData] = {}

    tilemap: pytmx.TiledMap = None

    def execute(self, context):
        try:
            self.tilemap = self.load_tilemap_file(self.filepath)
            self.create_material_for_tilesets()
            self.create_objects_for_layers()
            self.clean_up()
            return {'FINISHED'}
        except Exception as e:
            print(e)
            self.clean_up()
            return {'CANCELLED'}
        finally:
            self.clean_up()


    def clean_up(self):
        self.tilemap = None
        self.gid_to_tiledata_dict.clear()
        self.tileset_to_tiledata_dict.clear()


    def create_objects_for_layers(self):
        for layer in self.tilemap.visible_layers:
            if isinstance(layer, pytmx.TiledTileLayer):
                self.create_mesh_object(layer)


    def create_material_for_tilesets(self):
        for tileset in self.tilemap.tilesets:
            img = self.load_texture_image(tileset, self.filepath)
            mat = self.create_material(tileset.name, img)
            self.tileset_to_tiledata_dict.setdefault(tileset, TileData(material=mat, tileset=tileset, image=img))


    def load_tilemap_file(self, filepath):
        try:
            return pytmx.TiledMap(filepath)
        except FileNotFoundError:
            print(f"Error: File not found at {filepath}")


    def load_texture_image(self, tileset: pytmx.TiledTileset, filepath):
        # Get the texture path
        texture_path = bpy.path.abspath(os.path.join(os.path.dirname(filepath), tileset.source))
        return bpy.data.images.load(texture_path)


    def create_material(self, material_name: str, img: Image):
        # Create material
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


    def create_mesh_object(self, layer: pytmx.TiledTileLayer, tile_size=1):
        bm = bmesh.new()

        verts_map = {}  # Store vertices by their (x, y) coordinates

        uv_layer = bm.loops.layers.uv.verify()

        material_dict: dict[Material, int] = {}
        index = 0

        for x, y, gid in layer:
            if gid:  # gid is 0 if no tile
                verts = [self.get_or_create_vert(tile_size, bm, verts_map, Vector((x, y)) + LOOP_OFFSET_DICT[i]) for i in range(4)]
                # face_map.setdefault((x, -y), bm.faces.new(verts))
                face = bm.faces.new(verts)
                
                tiledata = self.get_tiledata_from_gid(gid)

                if tiledata.material not in material_dict:
                    material_dict.setdefault(tiledata.material, index)
                    index += 1

                face.material_index = material_dict.get(tiledata.material)

                local_gid = self.tilemap.tiledgidmap.get(gid) - tiledata.tileset.firstgid
                self.apply_uv_to_face(face, uv_layer, local_gid, tiledata)

        mesh = bpy.data.meshes.new(layer.name)
        bm.to_mesh(mesh)
        bm.free()

        obj = bpy.data.objects.new(layer.name, mesh)
        bpy.context.collection.objects.link(obj)

        sorted_materials = [material for material, index in sorted(material_dict.items(), key=lambda item: item[1])]

        if obj.data.materials:
            obj.data.materials.clear()

        for mat in sorted_materials:
            obj.data.materials.append(mat)

        return obj

    def get_tiledata_from_gid(self, gid):
        if gid in self.gid_to_tiledata_dict:
            return self.gid_to_tiledata_dict.get(gid)
        else:
            tileset = self.tilemap.get_tileset_from_gid(gid=gid)
            tiledata = self.tileset_to_tiledata_dict.get(tileset)
            return self.gid_to_tiledata_dict.setdefault(gid, tiledata)


    def get_or_create_vert(self, tile_size, bm: BMesh, verts_map, v: Vector):
        x, y = v
        return verts_map.get((x, -y)) or verts_map.setdefault((x, -y), bm.verts.new((x * tile_size, -y * tile_size, 0)))


    def apply_uv_to_face(self, face: BMFace, uv_layer, local_gid: int, tiledata: TileData):
        tile_x = local_gid % tiledata.columns
        tile_y = local_gid // tiledata.columns
        for i, loop in enumerate(face.loops):
            uv = (Vector((tile_x, tile_y)) + LOOP_OFFSET_DICT[i]) * Vector((tiledata.tile_width, - tiledata.tile_height)) + Vector((0, 1))
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