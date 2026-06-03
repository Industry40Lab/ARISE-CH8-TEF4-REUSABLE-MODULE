from launch import LaunchDescription
from launch.actions import TimerAction
from launch_ros.actions import Node

def generate_launch_description():
    
    # 1. Start RULA GUI immediately (t = 0s)
    rula_gui_node = Node(
        package='rula_gui',
        executable='rulaGui',
        name='rulaGui'
    )

    # 2. Start RULA Calculator after 1 second (t = 1s)
    rula_calculator_node = TimerAction(
        period=1.0,
        actions=[
            Node(
                package='rula_calculator',
                executable='rula_calculator',
                name='rula_calculator'
            )
        ]
    )

    # 3. Start Point 2D after 2 more seconds (t = 3s total)
    point_2d_node = TimerAction(
        period=3.0,
        actions=[
            Node(
                package='point_2D_extractor',
                executable='point_2D',
                name='point_2D',
                arguments=[
                    '--active_sides', '1', '2', '0', 
                    '--device_name', '947122070806', '213722071366', '213522072232'
                ]
            )
        ]
    )

    # 4. Start Ergonomic Assistant after 5 more seconds (t = 8s total)
    ergonomic_assistant_node = TimerAction(
        period=8.0,
        actions=[
            Node(
                package='rula_calculator',
                executable='pcb_ergonomic_assistant',
                name='pcb_ergonomic_assistant'
            )
        ]
    )

    return LaunchDescription([
        rula_gui_node,
        rula_calculator_node,
        point_2d_node,
        ergonomic_assistant_node
    ])