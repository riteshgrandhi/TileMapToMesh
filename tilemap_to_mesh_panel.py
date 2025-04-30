import bpy

class VIEW3D_PT_TileMapToMeshPanel(bpy.types.Panel):
    bl_idname = "VIEW3D_PT_TileMapToMeshPanel"
    bl_label = "TileMapToMesh"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "TileMapUtil"

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        obj = context.object

        box = layout.box()
        box.label(text="Import Tile Map")
        box.operator("tilemaputil.tilemap_loader")
        box.label(text="Import Ldtk")
        box.operator("tilemaputil.ldtk_loader")


# module classes
classes = (
    VIEW3D_PT_TileMapToMeshPanel,
)

def register():
    for cl in classes:
        bpy.utils.register_class(cl)

def unregister():
    for cl in classes:
        bpy.utils.unregister_class(cl)

if __name__ == '__main__':
    register()