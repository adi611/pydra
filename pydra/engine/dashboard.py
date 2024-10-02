# pydra/engine/dashboard.py

from bokeh.server.server import Server
from bokeh.application import Application
from bokeh.application.handlers.function import FunctionHandler
from bokeh.layouts import column, row
from bokeh.models import ColumnDataSource, DataTable, TableColumn, Select, Div, HoverTool, TapTool
from bokeh.plotting import figure
import networkx as nx
from bokeh.models import GraphRenderer, StaticLayoutProvider, Circle
import threading
from pydra.utils.messenger import AuditFlag
import os
import time

class Dashboard:
    def __init__(self, port=5006):
        self.port = port
        self.server = None
        self.thread = None
        self.workflow = None
        self.task_status = {}
        self.task_details = {}
        self.doc = None

    def start(self, workflow):
        self.workflow = workflow
        self.task_status = {task.name: 'waiting' for task in self.workflow.graph.nodes}
        self.task_details = {task.name: {} for task in self.workflow.graph.nodes}

        def create_dashboard(doc):
            self.doc = doc
            dag_plot = self.create_dag_plot()
            task_table = self.create_task_table()
            audit_info = self.create_audit_info()
            task_details = Div(text="", width=400)
            resource_plot = self.create_resource_plot()

            def update_task_details(attr, old, new):
                selected_task = new
                details = self.task_details.get(selected_task, {})
                task_details.text = f"""
                <h3>Task Details: {selected_task}</h3>
                <p><strong>Status:</strong> {self.task_status.get(selected_task, 'Unknown')}</p>
                <p><strong>Inputs:</strong> {details.get('inputs', 'Unknown')}</p>
                <p><strong>Outputs:</strong> {details.get('outputs', 'Unknown')}</p>
                <p><strong>Runtime:</strong> {details.get('runtime', 'Unknown')}</p>
                <p><strong>Error:</strong> {details.get('error', 'None')}</p>
                """

            task_select = Select(title="Select Task:", value="", options=[""] + list(self.task_status.keys()))
            task_select.on_change('value', update_task_details)

            doc.add_root(column(
                dag_plot,
                row(task_table, column(task_select, task_details)),
                audit_info,
                resource_plot
            ))

        self.server = Server({'/': Application(FunctionHandler(create_dashboard))}, port=self.port)
        self.thread = threading.Thread(target=self.server.io_loop.start)
        self.thread.start()
        print(f"Dashboard is running on http://localhost:{self.port}")

    def create_dag_plot(self):
        plot = figure(title=f"Workflow DAG: {self.workflow.name}", x_range=(-1.1, 1.1), y_range=(-1.1, 1.1),
                      tools="pan,wheel_zoom,box_zoom,reset,save", toolbar_location="above")

        graph = GraphRenderer()

        node_indices = list(range(len(self.workflow.graph.nodes)))
        graph.node_renderer.data_source.add(node_indices, 'index')
        graph.node_renderer.data_source.add([node.name for node in self.workflow.graph.nodes()], 'name')
        
        color_map = {'waiting': 'gray', 'running': 'yellow', 'completed': 'green', 'failed': 'red'}
        graph.node_renderer.data_source.add([color_map[self.task_status[task.name]] for task in self.workflow.graph.nodes()], 'color')
        
        graph.node_renderer.glyph = Circle(size=15, fill_color='color')

        pos = nx.spring_layout(self.workflow.graph)
        graph.layout_provider = StaticLayoutProvider(graph_layout={node: pos[node] for node in self.workflow.graph.nodes()})

        graph.edge_renderer.data_source.data = dict(
            start=[pos[src] for src, _ in self.workflow.graph.edges()],
            end=[pos[dst] for _, dst in self.workflow.graph.edges()]
        )

        plot.renderers.append(graph)

        hover = HoverTool(tooltips=[("Task", "@name"), ("Status", "@color")])
        plot.add_tools(hover)

        return plot

    def create_task_table(self):
        data = ColumnDataSource({
            "Task": list(self.task_status.keys()),
            "Status": list(self.task_status.values()),
        })
        columns = [
            TableColumn(field="Task", title="Task Name"),
            TableColumn(field="Status", title="Status"),
        ]
        return DataTable(source=data, columns=columns, width=400, height=200)

    def create_audit_info(self):
        audit_info = Div(text="", width=400)
        audit = self.workflow.audit
        audit_info.text = f"""
        <h3>Audit Information</h3>
        <p><strong>Audit Flags:</strong> {audit.audit_flags}</p>
        <p><strong>Messengers:</strong> {', '.join(str(m) for m in audit.messengers)}</p>
        <p><strong>Develop Mode:</strong> {audit.develop}</p>
        """
        return audit_info

    def create_resource_plot(self):
        plot = figure(title="Resource Usage", x_axis_label='Time', y_axis_label='Usage')
        self.resource_source = ColumnDataSource(data=dict(time=[], cpu=[], rss=[], vms=[]))
        plot.line('time', 'cpu', line_color="red", legend_label="CPU %", source=self.resource_source)
        plot.line('time', 'rss', line_color="blue", legend_label="RSS (MB)", source=self.resource_source)
        plot.line('time', 'vms', line_color="green", legend_label="VMS (MB)", source=self.resource_source)
        plot.legend.click_policy = "hide"
        return plot

    def update(self, task):
        status_info = task.get_status_info()
        self.task_status[task.name] = status_info['status']
        self.task_details[task.name] = status_info

        if self.workflow.audit.audit_check(AuditFlag.RESOURCE):
            # Read from the ResourceMonitor's log file
            log_file = os.path.join(self.workflow.output_dir, f"proc-{os.getpid()}_time-{time.time()}_freq-1.00.log")
            if os.path.exists(log_file):
                with open(log_file, 'r') as f:
                    lines = f.readlines()
                    if lines:
                        latest = lines[-1].strip().split(',')
                        if len(latest) == 4:
                            time, cpu, rss, vms = map(float, latest)
                            new_data = {
                                'time': [time],
                                'cpu': [cpu],
                                'rss': [rss],
                                'vms': [vms]
                            }
                            self.resource_source.stream(new_data)

        if self.doc:
            self.doc.add_next_tick_callback(self.update_document)

    def update_document(self):
        if self.doc is None:
            return
        
        # Update DAG plot
        dag_plot = self.doc.select_one({'type': figure, 'title': lambda x: x.startswith("Workflow DAG")})
        if dag_plot:
            graph_renderer = dag_plot.select_one({'type': GraphRenderer})
            if graph_renderer:
                color_map = {'waiting': 'gray', 'running': 'yellow', 'completed': 'green', 'failed': 'red'}
                graph_renderer.node_renderer.data_source.data['color'] = [color_map[self.task_status[task.name]] for task in self.workflow.graph.nodes()]

        # Update task table
        task_table = self.doc.select_one({'type': DataTable})
        if task_table:
            task_table.source.data = {
                "Task": list(self.task_status.keys()),
                "Status": list(self.task_status.values()),
            }

    def stop(self):
        if self.server:
            self.server.stop()
        if self.thread:
            self.thread.join()