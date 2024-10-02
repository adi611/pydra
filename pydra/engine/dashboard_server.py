# pydra/engine/dashboard_server.py

import threading
import json
from pathlib import Path
from datetime import datetime
from collections import defaultdict

from bokeh.server.server import Server
from bokeh.application import Application
from bokeh.application.handlers.function import FunctionHandler
from bokeh.layouts import column, row
from bokeh.models import ColumnDataSource, DataTable, TableColumn, Select, Div, HoverTool
from bokeh.plotting import figure
import networkx as nx
from bokeh.models import GraphRenderer, StaticLayoutProvider, Circle
from tornado.ioloop import IOLoop

class DashboardServer:
    def __init__(self, port=5006, data_dir=None):
        self.port = port
        self.data_dir = Path(data_dir) if data_dir else Path.home() / '.pydra_dashboard'
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.server = None
        self.thread = None
        self.workflows = defaultdict(dict)

    def start(self):
        def create_dashboard(doc):
            def update():
                self.load_workflow_data()
                workflow_select.options = [""] + list(self.workflows.keys())
                if workflow_select.value:
                    update_workflow_view(workflow_select.value)

            def update_workflow_view(workflow_id):
                if not workflow_id:
                    return
                
                workflow = self.workflows[workflow_id]
                workflow_info.text = f"""
                <h2>Workflow: {workflow['name']}</h2>
                <p><strong>Status:</strong> {workflow['status']}</p>
                <p><strong>Start Time:</strong> {workflow.get('start_time', 'N/A')}</p>
                <p><strong>End Time:</strong> {workflow.get('end_time', 'N/A')}</p>
                """
                
                task_source.data = {
                    'Task': [task['name'] for task in workflow['tasks']],
                    'Status': [task['status'] for task in workflow['tasks']]
                }
                
                update_dag(workflow)

            def update_dag(workflow):
                G = nx.DiGraph()
                for task in workflow['tasks']:
                    G.add_node(task['name'])
                # Add edges based on task dependencies (if available in your data)
                
                plot = figure(title=f"Workflow DAG: {workflow['name']}", x_range=(-1.1, 1.1), y_range=(-1.1, 1.1),
                              tools="pan,wheel_zoom,box_zoom,reset,save", toolbar_location="above")

                graph = GraphRenderer()

                node_indices = list(range(len(G.nodes)))
                graph.node_renderer.data_source.add(node_indices, 'index')
                graph.node_renderer.data_source.add(list(G.nodes()), 'name')
                
                color_map = {'waiting': 'gray', 'running': 'yellow', 'completed': 'green', 'failed': 'red', 'unknown': 'blue'}
                graph.node_renderer.data_source.add([color_map[task['status']] for task in workflow['tasks']], 'color')
                
                graph.node_renderer.glyph = Circle(size=15, fill_color='color')

                pos = nx.spring_layout(G)
                graph.layout_provider = StaticLayoutProvider(graph_layout={node: pos[node] for node in G.nodes()})

                graph.edge_renderer.data_source.data = dict(
                    start=[pos[src] for src, _ in G.edges()],
                    end=[pos[dst] for _, dst in G.edges()]
                )

                plot.renderers.append(graph)

                hover = HoverTool(tooltips=[("Task", "@name"), ("Status", "@color")])
                plot.add_tools(hover)

                dag_plot.children[0] = plot

            workflow_select = Select(title="Select Workflow:", value="", options=[""])
            workflow_select.on_change('value', lambda attr, old, new: update_workflow_view(new))

            workflow_info = Div(text="", width=400)

            task_source = ColumnDataSource({'Task': [], 'Status': []})
            columns = [
                TableColumn(field="Task", title="Task Name"),
                TableColumn(field="Status", title="Status"),
            ]
            task_table = DataTable(source=task_source, columns=columns, width=400, height=200)

            dag_plot = column(figure(title="Workflow DAG"))

            doc.add_root(column(
                workflow_select,
                workflow_info,
                row(task_table, dag_plot)
            ))

            doc.add_periodic_callback(update, 1000)  # Update every 1000 ms

        def run_server():
            self.server = Server({'/': Application(FunctionHandler(create_dashboard))}, port=self.port)
            self.server.start()
            print(f"Dashboard is running on http://localhost:{self.port}")
            IOLoop.current().start()

        self.thread = threading.Thread(target=run_server)
        self.thread.daemon = True
        self.thread.start()

    def stop(self):
        if self.server:
            IOLoop.current().add_callback(self.server.stop)
        if self.thread:
            self.thread.join()

    def update_workflow(self, workflow_id, data):
        file_path = self.data_dir / f"{workflow_id}.json"
        if data['status'] == 'started':
            data['start_time'] = datetime.now().isoformat()
        elif data['status'] in ['completed', 'failed']:
            data['end_time'] = datetime.now().isoformat()
        
        with file_path.open('w') as f:
            json.dump(data, f)

    def load_workflow_data(self):
        for file_path in self.data_dir.glob('*.json'):
            with file_path.open('r') as f:
                data = json.load(f)
            self.workflows[file_path.stem] = data

# Start the dashboard server when this module is imported
dashboard_server = DashboardServer()
dashboard_server.start()