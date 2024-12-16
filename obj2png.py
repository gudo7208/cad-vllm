import bpy
import math
import os
import glob
import argparse
from mathutils import Vector
from multiprocessing import Pool, cpu_count

class ThreeViewRenderer:
    """三视图渲染器类"""
    
    def __init__(self, obj_path, output_dir, resolution=1920, background_color=(1, 1, 1)):
        """
        初始化渲染器
        
        Args:
            obj_path: OBJ文件路径
            output_dir: 输出目录路径
            resolution: 渲染分辨率（默认1920x1080）
            background_color: 背景颜色（默认纯白色）
        """
        self.obj_path = obj_path
        self.output_dir = output_dir
        self.resolution = resolution
        self.background_color = background_color
        self._setup_scene()
        
    def _setup_scene(self):
        """设置场景基本参数"""
        # 清除默认场景
        bpy.ops.object.select_all(action='SELECT')
        bpy.ops.object.delete()
        
        # 设置GPU渲染
        prefs = bpy.context.preferences
        cycles_prefs = prefs.addons['cycles'].preferences
        # 启用所有可用的GPU设备
        cycles_prefs.get_devices()
        for device in cycles_prefs.devices:
            device.use = True
        
        # 设置渲染引擎和设备
        bpy.context.scene.render.engine = 'CYCLES'  # 使用Cycles引擎以支持GPU
        bpy.context.scene.cycles.device = 'GPU'
        
        # 优化渲染设置
        bpy.context.scene.cycles.samples = 32  # 降低采样数
        bpy.context.scene.cycles.use_denoising = True  # 启用降噪
        bpy.context.scene.cycles.use_adaptive_sampling = True  # 自适应采样
        bpy.context.scene.cycles.adaptive_threshold = 0.01
        bpy.context.scene.cycles.adaptive_min_samples = 16
        
        # 导入OBJ模型
        bpy.ops.import_scene.obj(filepath=self.obj_path)
        
        # 选择导入的模型
        obj = bpy.context.selected_objects[0]
        
        # 重置模型变换
        self._reset_model_transform(obj)
        
        # 设置输出分辨率
        bpy.context.scene.render.resolution_x = self.resolution
        bpy.context.scene.render.resolution_y = self.resolution
        bpy.context.scene.render.resolution_percentage = 100
        bpy.context.scene.render.image_settings.file_format = 'PNG'
        bpy.context.scene.render.image_settings.color_mode = 'RGBA'
        
        # 创建世界环境
        if bpy.context.scene.world is None:
            world = bpy.data.worlds.new("World")
            bpy.context.scene.world = world
        
        # 设置背景颜色
        world = bpy.context.scene.world
        world.use_nodes = True
        bg = world.node_tree.nodes['Background']
        bg.inputs[0].default_value = (*self.background_color, 1)
        bg.inputs[1].default_value = 1.0
        
        # 设置模型材质和边缘显示
        self._setup_model_material(obj)
        
        # 创建单一柔和光源
        self._add_sun_light(rotation=(math.radians(45), math.radians(45), 0), energy=3.0)
        
        # 设置相机为正交投影
        self.camera = bpy.data.objects.new("Camera", bpy.data.cameras.new("Camera"))
        bpy.context.scene.collection.objects.link(self.camera)
        bpy.context.scene.camera = self.camera
        self.camera.data.type = 'ORTHO'
        
        # 自动调整相机视图以适应模型
        self._auto_adjust_camera(obj)

    def _reset_model_transform(self, obj):
        """重置模型变换"""
        # 选择对象
        bpy.context.view_layer.objects.active = obj
        obj.select_set(True)
        
        # 应用所有变换
        bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
        
        # 重置原点到几何中心
        bpy.ops.object.origin_set(type='ORIGIN_GEOMETRY', center='BOUNDS')
        
        # 将对象移动到世界原点
        obj.location = (0, 0, 0)
        
        # 确保对象正确朝向（Z轴向上）
        obj.rotation_euler = (0, 0, 0)
        
        # 标准化尺寸
        dimensions = obj.dimensions
        max_dim = max(dimensions)
        if max_dim != 0:
            scale_factor = 2.0 / max_dim  # 将最大尺寸标准化为2个单位
            obj.scale = (scale_factor, scale_factor, scale_factor)
        
        # 应用缩放
        bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
        
    def _setup_model_material(self, obj):
        """设置模型材质和边缘显示"""
        # 启用边缘显示
        bpy.context.scene.render.use_freestyle = True
        bpy.context.scene.view_layers[0].use_freestyle = True
        
        # 配置边缘线条设置
        freestyle_settings = bpy.context.scene.view_layers[0].freestyle_settings
        
        # 清除现有的线条集
        for lineset in freestyle_settings.linesets:
            freestyle_settings.linesets.remove(lineset)
        
        # 创建新的线条集
        lineset = freestyle_settings.linesets.new('EdgeLines')
        
        # 设置基本边缘检测
        lineset.select_silhouette = True
        lineset.select_crease = True
        lineset.select_border = True
        
        # 设置线条样式
        linestyle = lineset.linestyle
        linestyle.color = (0.0, 0.0, 0.4)  # 深蓝色边线
        linestyle.thickness = 1.5  # 线条粗细
        
        # 创建新材质
        mat = bpy.data.materials.new(name="ModelMaterial")
        mat.use_nodes = True
        nodes = mat.node_tree.nodes
        
        # 清除默认节点
        nodes.clear()
        
        # 创建主体材质节点
        principled = nodes.new('ShaderNodeBsdfPrincipled')
        principled.inputs['Base Color'].default_value = (0.3, 0.4, 0.5, 1)  # 浅蓝灰色
        principled.inputs['Metallic'].default_value = 0.7  # 金属度
        principled.inputs['Roughness'].default_value = 0.2  # 光滑度
        
        # 创建输出节点
        output = nodes.new('ShaderNodeOutputMaterial')
        
        # 连接节点
        mat.node_tree.links.new(principled.outputs[0], output.inputs[0])
        
        # 应用材质到模型
        if obj.data.materials:
            obj.data.materials[0] = mat
        else:
            obj.data.materials.append(mat)
        
    def _add_sun_light(self, rotation, energy):
        """添加太阳灯光"""
        bpy.ops.object.light_add(type='SUN')
        sun = bpy.context.active_object
        sun.rotation_euler = rotation
        sun.data.energy = energy
        # 启用柔和阴影
        sun.data.use_shadow = True
        sun.data.shadow_soft_size = 2.0
        
    def _set_camera_position(self, position, rotation):
        """设置相机位置和旋转"""
        self.camera.location = position
        self.camera.rotation_euler = rotation
        
    def _auto_adjust_camera(self, obj):
        """根据模型尺寸自动调整相机正交尺寸"""
        # 计算模型的边界框
        bbox_corners = [obj.matrix_world @ Vector(corner) for corner in obj.bound_box]
        bbox_min = Vector(map(min, zip(*bbox_corners)))
        bbox_max = Vector(map(max, zip(*bbox_corners)))
        
        # 计算模型的尺寸
        dimensions = bbox_max - bbox_min
        max_dim = max(dimensions)
        
        # 设置相机正交尺寸，确保完全包含模型
        self.camera.data.ortho_scale = max_dim * 1.2  # 留出20%的边距
        
        # 确保模型位于原点
        center = (bbox_max + bbox_min) / 2
        obj.location = -center
    
    def render_view(self, view_name, position, rotation):
        """渲染指定视图"""
        self._set_camera_position(position, rotation)
        output_path = os.path.join(self.output_dir, f"{view_name}.png")
        bpy.context.scene.render.filepath = output_path
        bpy.ops.render.render(write_still=True)
        print(f"已渲染 {view_name} 视图: {output_path}")
        
    def render_all_views(self):
        """渲染所有视图"""
        # 标准正交视图（六视图）
        orthographic_views = {
            "front": ((0, -15, 0), (math.radians(90), 0, math.radians(180))),  # 正视图
            "back": ((0, 15, 0), (math.radians(90), 0, 0)),                    # 后视图
            "right": ((15, 0, 0), (math.radians(90), 0, math.radians(90))),    # 右视图
            "left": ((-15, 0, 0), (math.radians(90), 0, math.radians(-90))),   # 左视图
            "top": ((0, 0, 15), (0, 0, math.radians(180))),                    # 俯视图
            "bottom": ((0, 0, -15), (math.radians(180), 0, math.radians(180))) # 仰视图
        }
        
        # 等轴测视图（四个方向）
        iso_distance = 15  # 相机距离
        iso_angle = math.radians(54.736)  # arctan(1/√2)，标准等轴测角度
        iso_views = {
            "standard": (  # 前右上等轴测（标准视图）
                (iso_distance, -iso_distance, iso_distance),
                (iso_angle, 0, math.radians(45))
            ),
            "iso_back": (  # 后左上等轴测
                (-iso_distance, iso_distance, iso_distance),
                (iso_angle, 0, math.radians(225))
            ),
            "iso_left": (  # 前左上等轴测
                (-iso_distance, -iso_distance, iso_distance),
                (iso_angle, 0, math.radians(315))
            ),
            "iso_right": ( # 后右上等轴测
                (iso_distance, iso_distance, iso_distance),
                (iso_angle, 0, math.radians(135))
            )
        }
        
        # 渲染正交视图
        print("\n正在渲染正交视图...")
        for view_name, (position, rotation) in orthographic_views.items():
            self.render_view(view_name, position, rotation)
            
        # 渲染等轴测视图
        print("\n正在渲染等轴测视图...")
        for view_name, (position, rotation) in iso_views.items():
            self.render_view(view_name, position, rotation)

def process_single_model(args):
    """处理单个模型的渲染任务"""
    obj_path, output_dir, resolution = args
    try:
        # 创建输出目录
        model_output_dir = os.path.join(output_dir, os.path.splitext(os.path.basename(obj_path))[0])
        os.makedirs(model_output_dir, exist_ok=True)
        
        # 渲染模型
        renderer = ThreeViewRenderer(
            obj_path=obj_path,
            output_dir=model_output_dir,
            resolution=resolution,
            background_color=(1, 1, 1)
        )
        renderer.render_all_views()
        return f"成功渲染: {obj_path}"
    except Exception as e:
        return f"渲染失败 {obj_path}: {str(e)}"

def batch_render(input_dir, output_dir, resolution=1920, num_processes=None):
    """批量渲染处理
    
    Args:
        input_dir: 包含OBJ文件的输入目录
        output_dir: 渲染结果输出目录
        resolution: 渲染分辨率
        num_processes: 并行进程数，默认为CPU核心数
    """
    # 获取所有OBJ文件
    obj_files = glob.glob(os.path.join(input_dir, "**/*.obj"), recursive=True)
    
    if not obj_files:
        print(f"在 {input_dir} 中未找到OBJ文件")
        return
    
    # 设置进程数
    if num_processes is None:
        num_processes = cpu_count()
    
    # 准备渲染参数
    render_args = [(obj_file, output_dir, resolution) for obj_file in obj_files]
    
    # 使用进程池并行处理
    print(f"开始并行渲染，使用 {num_processes} 个进程...")
    with Pool(num_processes) as pool:
        results = pool.map(process_single_model, render_args)
    
    # 输出结果
    for result in results:
        print(result)

def main():
    """主函数"""
    parser = argparse.ArgumentParser(description='批量渲染OBJ模型的多视图')
    parser.add_argument('--input_dir', type=str, required=True, help='输入目录路径，包含OBJ文件')
    parser.add_argument('--output_dir', type=str, required=True, help='输出目录路径')
    parser.add_argument('--resolution', type=int, default=1920, help='渲染分辨率')
    parser.add_argument('--processes', type=int, default=None, help='并行进程数，默认为CPU核心数')
    
    args = parser.parse_args()
    
    # 确保输出目录存在
    os.makedirs(args.output_dir, exist_ok=True)
    
    # 执行批量渲染
    batch_render(
        input_dir=args.input_dir,
        output_dir=args.output_dir,
        resolution=args.resolution,
        num_processes=args.processes
    )

if __name__ == "__main__":
    main()
