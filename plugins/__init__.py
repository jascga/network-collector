"""
plugins 包 — 场景插件集合

每个子目录是一个独立的场景插件（如 eip_conflict_check/）。
插件入口约定：
  - SCENE: 场景元数据
  - DEVICE_RULES: 设备筛选规则
  - COMMAND_MAPPING: 设备→命令映射
  - BUNDLED_COMMANDS: 自带命令
  - INPUT_PARAMS: 输入参数定义
  - render_task_form(stage, context): UI 渲染
  - RESULT_LAYOUT: 结果布局
  - analyze(task_dir, parsed_data, params): 分析函数
"""
