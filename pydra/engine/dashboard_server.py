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
from bokeh.models import ColumnDataSource, DataTable, TableColumn, Select, Div, HoverTool, MultiLine
from bokeh.plotting import figure
import networkx as nx
from bokeh.models import GraphRenderer, StaticLayoutProvider, Circle
from tornado.ioloop import IOLoop

class DashboardServer:
    def __init__(self, port=5006, data_dir=None):
        print("Initializing DashboardServer")
        self.port = port
        self.data_dir = Path(data_dir) if data_dir else Path.home() / '.pydra_dashboard'
        print(f"Data directory set to: {self.data_dir}")
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.server = None
        self.thread = None
        self.workflows = defaultdict(dict)

    def start(self):
        print("Starting DashboardServer")
        def create_dashboard(doc):
            print("Creating dashboard")
            def update():
                print("Updating dashboard")
                self.load_workflow_data()
                workflow_select.options = [""] + list(self.workflows.keys())
                if workflow_select.value:
                    update_workflow_view(workflow_select.value)

            def update_workflow_view(workflow_id):
                print(f"Updating workflow view for workflow_id: {workflow_id}")
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
                
                new_plot = update_dag(workflow)
                dag_plot.children[0] = new_plot

            def update_dag(workflow):
                print(f"Updating DAG for workflow: {workflow['name']}")
                G = nx.DiGraph()
                for task in workflow['tasks']:
                    G.add_node(task['name'])
                # Add edges based on task dependencies
                for task in workflow['tasks']:
                    for dep in task.get('dependencies', []):
                        G.add_edge(dep, task['name'])
                
                print(f"Tasks: {[task['name'] for task in workflow['tasks']]}")
                print(f"Dependencies: {[(dep, task['name']) for task in workflow['tasks'] for dep in task.get('dependencies', [])]}")

                plot = figure(title=f"Workflow DAG: {workflow['name']}", tools="pan,wheel_zoom,reset", toolbar_location="above")

                graph = GraphRenderer()

                node_indices = list(range(len(G.nodes)))
                graph.node_renderer.data_source.add(node_indices, 'index')
                graph.node_renderer.data_source.add(list(G.nodes()), 'name')
                
                color_map = {'waiting': 'gray', 'running': 'yellow', 'completed': 'green', 'failed': 'red', 'unknown': 'blue'}
                graph.node_renderer.data_source.add([color_map.get(task['status'], 'gray') for task in workflow['tasks']], 'color')
                
                graph.node_renderer.glyph = Circle(radius=0.2, fill_color='color')  # Increased radius

                pos = nx.spring_layout(G)
                print(f"Positions: {pos}")
                graph.layout_provider = StaticLayoutProvider(graph_layout={node: pos[node] for node in G.nodes()})

                start_points = []
                end_points = []
                for start, end in G.edges():
                    start_points.append(pos[start])
                    end_points.append(pos[end])

                graph.edge_renderer.data_source.data = dict(
                    start=start_points,
                    end=end_points
                )

                graph.edge_renderer.glyph = MultiLine(line_color="black", line_alpha=0.8, line_width=1)
                plot.renderers.append(graph)

                hover = HoverTool(tooltips=[("Task", "@name"), ("Status", "@color")])
                plot.add_tools(hover)

                return plot

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
            print("Running server")
            self.server = Server({'/': Application(FunctionHandler(create_dashboard))}, port=self.port)
            self.server.start()
            print(f"Dashboard is running on http://localhost:{self.port}")
            IOLoop.current().start()

        self.thread = threading.Thread(target=run_server)
        self.thread.daemon = True
        self.thread.start()
        print("DashboardServer started")

    def stop(self):
        print("Stopping DashboardServer")
        if self.server:
            IOLoop.current().add_callback(self.server.stop)
        if self.thread:
            self.thread.join()
        print("DashboardServer stopped")

    def update_workflow(self, workflow_id, data):
        print(f"Updating workflow: {workflow_id} with data: {data}")
        file_path = self.data_dir / f"{workflow_id}.json"
        if data['status'] == 'started':
            data['start_time'] = datetime.now().isoformat()
        elif data['status'] in ['completed', 'failed']:
            data['end_time'] = datetime.now().isoformat()
        
        with file_path.open('w') as f:
            json.dump(data, f)
        print(f"Workflow {workflow_id} updated")

    def load_workflow_data(self):
        print("Loading workflow data")
        for file_path in self.data_dir.glob('*.json'):
            with file_path.open('r') as f:
                data = json.load(f)
            self.workflows[file_path.stem] = data
        print("Workflow data loaded")

# Start the dashboard server when this module is imported
dashboard_server = DashboardServer()
dashboard_server.start()

# pydra/engine/dashboard_server_dash.py

# import threading
# import json
# from pathlib import Path
# from datetime import datetime
# from collections import defaultdict
# import dash
# from dash import dcc, html
# from dash.dependencies import Input, Output
# from dash import dash_table
# import networkx as nx
# import plotly.graph_objects as go
# import os

# class DashboardServerDash:
#     def __init__(self, port=8050, data_dir=None):
#         print("Initializing DashboardServerDash")
#         self.port = port
#         self.data_dir = Path(data_dir) if data_dir else Path.home() / '.pydra_dashboard'
#         print(f"Data directory set to: {self.data_dir}")
#         self.data_dir.mkdir(parents=True, exist_ok=True)
#         self.server = None
#         self.thread = None
#         self.workflows = defaultdict(dict)
#         self.app = dash.Dash(__name__)

#         # Load initial workflow data
#         self.load_workflow_data()

#         # Set up the layout of the Dash application
#         self.app.layout = html.Div([
#             dcc.Dropdown(
#                 id='workflow-dropdown',
#                 options=[{'label': name, 'value': name} for name in self.workflows.keys()],
#                 placeholder="Select a workflow"
#             ),
#             html.Div(id='workflow-info'),
#             dash_table.DataTable(
#                 id='task-table',
#                 columns=[{'name': 'Task Name', 'id': 'Task'}, {'name': 'Status', 'id': 'Status'}],
#                 data=[]
#             ),
#             dcc.Graph(id='dag-graph')
#         ])

#         # Define the callback to update the workflow details
#         @self.app.callback(
#             Output('workflow-info', 'children'),
#             Output('task-table', 'data'),
#             Output('dag-graph', 'figure'),
#             Input('workflow-dropdown', 'value')
#         )
#         def update_dashboard(workflow_id):
#             if not workflow_id:
#                 return "", [], go.Figure()

#             workflow = self.workflows.get(workflow_id, {})
#             if not workflow:
#                 return "Workflow not found.", [], go.Figure()

#             # Workflow info section
#             workflow_info = html.Div([
#                 html.H2(f"Workflow: {workflow['name']}"),
#                 html.P(f"Status: {workflow['status']}"),
#                 html.P(f"Start Time: {workflow.get('start_time', 'N/A')}"),
#                 html.P(f"End Time: {workflow.get('end_time', 'N/A')}")
#             ])

#             # Task data for the table
#             task_data = [{'Task': task['name'], 'Status': task['status']} for task in workflow['tasks']]

#             # DAG plot using Plotly for the graph
#             dag_figure = self.create_dag_graph(workflow)

#             return workflow_info, task_data, dag_figure

#     def create_dag_graph(self, workflow):
#         G = nx.DiGraph()
#         for task in workflow['tasks']:
#             G.add_node(task['name'])

#         # Add edges based on task dependencies (if available in your data)
#         pos = nx.spring_layout(G)

#         edge_x = []
#         edge_y = []
#         for edge in G.edges():
#             x0, y0 = pos[edge[0]]
#             x1, y1 = pos[edge[1]]
#             edge_x.append(x0)
#             edge_x.append(x1)
#             edge_x.append(None)
#             edge_y.append(y0)
#             edge_y.append(y1)
#             edge_y.append(None)

#         edge_trace = go.Scatter(
#             x=edge_x, y=edge_y,
#             line=dict(width=2, color='gray'),
#             hoverinfo='none',
#             mode='lines'
#         )

#         node_x = []
#         node_y = []
#         node_text = []
#         for node in G.nodes():
#             x, y = pos[node]
#             node_x.append(x)
#             node_y.append(y)
#             node_text.append(f"{node}: {workflow['tasks'][G.nodes[node]]['status']}")

#         node_trace = go.Scatter(
#             x=node_x, y=node_y,
#             mode='markers+text',
#             text=node_text,
#             textposition='bottom center',
#             marker=dict(
#                 showscale=True,
#                 colorscale='YlGnBu',
#                 size=10,
#                 color=[workflow['tasks'][i]['status'] for i in G.nodes()],
#                 colorbar=dict(
#                     thickness=15,
#                     title='Task Status',
#                     xanchor='left',
#                     titleside='right'
#                 ),
#                 line_width=2)
#         )

#         fig = go.Figure(data=[edge_trace, node_trace],
#                         layout=go.Layout(
#                             title=f"Workflow DAG: {workflow['name']}",
#                             showlegend=False,
#                             hovermode='closest',
#                             margin=dict(b=0, l=0, r=0, t=40),
#                             xaxis=dict(showgrid=False, zeroline=False),
#                             yaxis=dict(showgrid=False, zeroline=False))
#                         )
#         return fig

#     def start(self):
#         print("Starting DashboardServerDash")
#         def run_server():
#             print(f"Dashboard is running on http://localhost:{self.port}")
#             self.app.run_server(port=self.port)

#         self.thread = threading.Thread(target=run_server)
#         self.thread.daemon = True
#         self.thread.start()
#         print("DashboardServerDash started")

#     def stop(self):
#         print("Stopping DashboardServerDash")
#         # Stop the Dash server (thread cleanup not necessary for Dash)
#         print("DashboardServerDash stopped")

#     def update_workflow(self, workflow_id, data):
#         print(f"Updating workflow: {workflow_id} with data: {data}")
#         file_path = self.data_dir / f"{workflow_id}.json"
#         if data['status'] == 'started':
#             data['start_time'] = datetime.now().isoformat()
#         elif data['status'] in ['completed', 'failed']:
#             data['end_time'] = datetime.now().isoformat()

#         with file_path.open('w') as f:
#             json.dump(data, f)
#         print(f"Workflow {workflow_id} updated")

#     def load_workflow_data(self):
#         print("Loading workflow data")
#         for file_path in self.data_dir.glob('*.json'):
#             with file_path.open('r') as f:
#                 data = json.load(f)
#             self.workflows[file_path.stem] = data
#         print("Workflow data loaded")

# # Start the dashboard server when this module is imported
# dashboard_server_dash = DashboardServerDash()
# dashboard_server_dash.start()

