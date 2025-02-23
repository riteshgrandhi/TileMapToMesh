import os
import bpy
import pytmx
import bmesh
from bpy_extras.io_utils import ImportHelper


# class Utils:
#     @staticmethod
#     def get_key(x, y):
#         return f"{x}_{y}"


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
        print(f"Hello from {self.bl_idname} - rittu")
        tilemap = UTIL_OP_LoadTilemap.load_tilemap_file(context, self.filepath)

        obj = self.create_mesh_object(tilemap)

        mat = self.create_material(tilemap, self.filepath)

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

    
    def create_material(self, tilemap, filepath):
        if tilemap.tilesets:
            tileset = tilemap.tilesets[0]  # Assuming one tileset

            # Get the texture path
            texture_path = bpy.path.abspath(os.path.join(os.path.dirname(filepath), tileset.source))
            # texture_path = bpy.path.abspath(tileset.source)

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
            texture_node = material.node_tree.nodes.new("ShaderNodeTexImage")

            texture_node.image = bpy.data.images.load(texture_path)
            texture_node.interpolation = 'Closest' #pixel art filtering

            # Link nodes
            material.node_tree.links.new(emission_node.inputs["Color"], texture_node.outputs["Color"])
            material.node_tree.links.new(output_node.inputs["Surface"], emission_node.outputs["Emission"])

            return material

    
    def create_mesh_object(self, tilemap, tile_size=1):
        try:
            bm = bmesh.new()

            verts_map = {}  # Store vertices by their (x, y) coordinates

            for layer in tilemap.visible_layers:
                if isinstance(layer, pytmx.TiledTileLayer):
                    for x, y, gid in layer:
                        if gid:  # gid is 0 if no tile
                            # Get or create vertices
                            v1 = self.get_or_create_vert(tile_size, bm, verts_map, x, y)
                            v2 = self.get_or_create_vert(tile_size, bm, verts_map, x + 1, y)
                            v3 = self.get_or_create_vert(tile_size, bm, verts_map, x + 1, y + 1)
                            v4 = self.get_or_create_vert(tile_size, bm, verts_map, x, y + 1)

                            bm.faces.new((v1, v2, v3, v4))
            mesh = bpy.data.meshes.new("TilemapMesh")
            bm.to_mesh(mesh)
            bm.free()

            obj = bpy.data.objects.new("Tilemap", mesh)
            bpy.context.collection.objects.link(obj)

            return obj
        except Exception as e:
            print(f"An error occurred: {e}")

    def get_or_create_vert(self, tile_size, bm, verts_map, x, y):
        return verts_map.get((x, -y)) or verts_map.setdefault((x, -y), bm.verts.new((x * tile_size, -y * tile_size, 0)))

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