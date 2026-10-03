import bpy
import bmesh
import os


def remove_object(blender_object):
    data = blender_object.data

    bpy.data.objects.remove(blender_object)
    if data is not None:
        bpy.data.meshes.remove(data)

def create_projected_mesh(configuration, frame_start=0, frame_end=0):
    name = "NewWiperMaskObject"

    # create the mesh data
    mesh_data = bpy.data.meshes.new(f"{name}_data")

    # create the mesh object using the mesh data
    mesh_obj = bpy.data.objects.new(name, mesh_data)

    # add the mesh object into the scene
    bpy.context.scene.collection.objects.link(mesh_obj)

    # create a new bmesh
    bm = bmesh.new()

    boundaries_vertices_indexes = []
    vertices = []
    j = 0
    for i in range(frame_start, frame_end):
        bpy.context.scene.frame_set(i)
        vertices.append(configuration.wiper_point_a.matrix_world.to_translation())
        j += 1
        vertices.append(configuration.wiper_point_b.matrix_world.to_translation())
        j += 1

        if i not in (frame_start, frame_end - 1):
            boundaries_vertices_indexes.append(j - 1)
            boundaries_vertices_indexes.append(j - 2)

    # create and add a vertices
    for vertice in vertices:
        bm.verts.new(vertice)

    face_vert_indices = []
    # create a list of vertex indices that are part of a given face
    for i in range(0, len(vertices) - 2, 2):
        face_vert_indices.append((i, i + 1, i + 3, i + 2))

    bm.verts.ensure_lookup_table()

    for vert_indices in face_vert_indices:
        bm.faces.new([bm.verts[index] for index in vert_indices])

    # writes the bmesh data into the mesh data
    bm.to_mesh(mesh_data)

    # [Optional] update the mesh data (helps with redrawing the mesh in the viewport)
    mesh_data.update()

    # clean up/free memory that was allocated for the bmesh
    bm.free()

    # Set auto_smooth on mesh
    if bpy.app.version < (4, 0, 0):
        mesh_data.use_auto_smooth = True

    # Create a vertex group containing all vertices but not boundaries
    bpy.ops.object.select_all(action="DESELECT")
    bpy.context.view_layer.objects.active = mesh_obj

    bpy.ops.object.vertex_group_add()
    vg = mesh_obj.vertex_groups.active
    vg.name = "all_without_boundaries"
    vg.add(index=boundaries_vertices_indexes, weight=1, type="REPLACE")
    
    # bpy.ops.object.mode_set(mode="EDIT")
    # bpy.ops.mesh.select_all(action="SELECT")
    # bpy.ops.uv.unwrap(method="ANGLE_BASED", margin=0.001)
    # bpy.ops.object.mode_set(mode="OBJECT")

    return mesh_obj

def saturate(x):
    return max(0, min(1, x))

def remap(original_value, original_min, original_max, new_min, new_max):
    saturated_value = saturate(
        float(
            float(original_value - original_min) 
            / float(original_max - original_min)
        )
    )
    return new_min + (new_max - new_min) * saturated_value

def get_v_color_by_frame(frame, frame_start, frame_end, border):
    v_color = [0, 0, 0, 1]

    color_value = remap(frame, frame_start, frame_end, 0, 255) / 255

    v_color[0] = color_value
    v_color[1] = 1 - color_value  # invert r

    if border:
        v_color[2] = 0
    else:
        v_color[2] = 1

    return v_color

def set_v_colors(mesh, frame_start, frame_end):
    if bpy.app.version < (4, 0, 0):
        mesh.sculpt_vertex_colors.new()
    else:
        color_attribute = mesh.color_attributes.new(name="Color_Wipers", type="FLOAT_COLOR", domain="POINT")

    vIndex = 0
    for i in range(frame_start, frame_end):
        color = get_v_color_by_frame(i, frame_start, frame_end, False)
        
        if bpy.app.version < (4, 0, 0):
            mesh.sculpt_vertex_colors[0].data[vIndex].color = color
        else:
            color_attribute.data[vIndex].color = color
            
        color = get_v_color_by_frame(i, frame_start, frame_end, True)
        if bpy.app.version < (4, 0, 0):
            mesh.sculpt_vertex_colors[0].data[vIndex + 1].color = color
        else:
            color_attribute.data[vIndex + 1].color = color
            
        vIndex += 2

def subdivide_wiper_object(obj):
    bpy.ops.object.select_all(action="DESELECT")
    bpy.context.view_layer.objects.active = obj

    # Add subdivision modifier
    modifier = obj.modifiers.new(type="SUBSURF", name="subdivide")
    modifier.subdivision_type = "SIMPLE"
    modifier.levels = 3

    # Apply modifier
    bpy.ops.object.modifier_apply(modifier=modifier.name)

def smooth_wiper_object(obj):
    bpy.ops.object.select_all(action="DESELECT")
    bpy.context.view_layer.objects.active = obj

    # Add subdivision modifier
    modifier = obj.modifiers.new(type="LAPLACIANSMOOTH", name="smooth")
    modifier.iterations = 4
    modifier.lambda_factor = 0
    modifier.lambda_border = 6
    modifier.vertex_group = obj.vertex_groups[0].name

    # Apply modifier
    bpy.ops.object.modifier_apply(modifier=modifier.name)

def prepare_wiper_material(obj):
    bpy.ops.object.select_all(action="DESELECT")
    bpy.context.view_layer.objects.active = obj

    old_area = bpy.context.area.ui_type
    bpy.context.area.ui_type = "ShaderNodeTree"

    material_count = len(bpy.data.materials)
    bpy.ops.material.new()
    material = bpy.data.materials["Material"]
    material.name = f"Material_{material_count}" 

    material.use_nodes = True
    obj.data.materials.append(material)

    nodes = material.node_tree.nodes
    links = material.node_tree.links

    vertex_color_node = nodes.new("ShaderNodeVertexColor")
    vertex_color_node.location = (-200, 200)
    if bpy.app.version < (4, 0, 0):
        vertex_color_node.layer_name = "Col"
    else:
        vertex_color_node.layer_name = "Color_Wipers"

    principled = nodes["Principled BSDF"]

    links.new(vertex_color_node.outputs[0], principled.inputs[0])

    bpy.context.area.ui_type = old_area

def prepare_windshield_material(obj, img):
    if img is None:
        return
    
    bpy.ops.object.select_all(action="DESELECT")
    
    bpy.context.view_layer.objects.active = obj
    
    if len(obj.data.materials) <= 0:
        return
        
    material = obj.active_material
    material.use_nodes = True

    nodes = material.node_tree.nodes

    if img.name in nodes:
        texture_node = nodes[img.name]
    else:
        texture_node = nodes.new(type="ShaderNodeTexImage")
        
    texture_node.name = img.name
    texture_node.image = img
    
    for node in nodes:
        node.select = False
        
    texture_node.select = True
    nodes.active = texture_node
    

def clean_windshield_material(obj, nodeName):
    bpy.ops.object.select_all(action="DESELECT")
    bpy.context.view_layer.objects.active = obj

    if len(obj.data.materials) <= 0:
        return
    
    material = obj.active_material
    nodes = material.node_tree.nodes
    if nodes.find(nodeName) > -1:
        texture_node = nodes[nodeName]
        nodes.remove(texture_node)

def prepare_output_texture(
    name="wiperMask",
    output_texture_size=2048,
    output_path=None
):
    old_area = bpy.context.area.ui_type
    bpy.context.area.ui_type = "IMAGE_EDITOR"

    output_path = os.path.join(output_path, name + ".png")
    if os.path.exists(output_path):
        try:
            os.remove(output_path)
        except PermissionError:
            print(f"File {output_path} is readonly.")

    if name in bpy.data.images:
        bpy.data.images.remove(bpy.data.images[name])

    bpy.ops.image.new(
        name=name,
        color=(0, 0, 0, 0),
        width=output_texture_size,
        height=output_texture_size
    )
    img = bpy.data.images[name]

    bpy.context.area.spaces.active.image = img
    bpy.ops.image.save_as(filepath=output_path)

    bpy.context.area.ui_type = old_area

def bake_texture(
    start_time=0,
    end_time=0,
    configurations=None,
    output_texture_name="",
    output_texture_size=1024,
    output_path=""
):
    ## Set render engine to cycles
    old_engine = bpy.context.scene.render.engine
    bpy.context.scene.render.engine = "CYCLES"

    ## Setup output path
    prepare_output_texture(
        name=output_texture_name,
        output_texture_size=output_texture_size,
        output_path=output_path
    )

    ## Clear output texture
    output_texture = bpy.data.images[output_texture_name]
    output_texture.source = "FILE"
    if bpy.app.version < (4, 0, 0):
        output_texture.colorspace_settings.name = "Linear"
    else:
        output_texture.colorspace_settings.name = "Linear Rec.709"

    wiper_mask_objects = []
    for configuration in configurations:
        ## Setup material for windshield node
        prepare_windshield_material(configuration.windshield_object, output_texture)

        ## Create new object following the animation of the wipers
        wiper_mask_object = create_projected_mesh(configuration, start_time, end_time)
        wiper_mask_objects.append(wiper_mask_object)

        ## Set Vertex Colors following the animation of the wipers
        set_v_colors(wiper_mask_object.data, start_time, end_time)

        ## Smooth wiper object
        subdivide_wiper_object(wiper_mask_object)
        smooth_wiper_object(wiper_mask_object)

        ## Setup the material of the wiper object
        prepare_wiper_material(wiper_mask_object)

        ## select wiperobject to windshield node
        bpy.ops.object.select_all(action="DESELECT")
        wiper_mask_object.select_set(True)
        configuration.windshield_object.select_set(True)

        ## Set windshield node as active object
        bpy.context.view_layer.objects.active = configuration.windshield_object

        ## Bake vcolors of wiperobject to windshield node
        bpy.ops.object.bake(
            type="DIFFUSE",
            pass_filter={"COLOR"},
            use_selected_to_active=True,
            use_clear=False,
            cage_extrusion=0.1,
            max_ray_distance=0.5
        )

        ## Clean Windshild nodes material
        clean_windshield_material(configuration.windshield_object, output_texture_name)

    ## Save output texture
    old_area = bpy.context.area.ui_type
    bpy.context.area.ui_type = "IMAGE_EDITOR"
    bpy.context.area.spaces.active.image = output_texture
    bpy.ops.image.save()

    ## Restore context
    bpy.context.area.ui_type = old_area
    bpy.context.scene.render.engine = old_engine

    ## Clean generated wiper mask objects after bake
    for wiper_mask_object in wiper_mask_objects:
        remove_object(wiper_mask_object)
