from http.server import HTTPServer, BaseHTTPRequestHandler
import json
import urllib.parse
from uuid import uuid4
from datetime import datetime

tasks = {
    "1": {
        "id": "1",
        "title": "Complete project proposal",
        "description": "Write and submit the project proposal for the new client",
        "completed": False,
        "created_at": "2024-08-15T09:00:00"
    },
    "2": {
        "id": "2",
        "title": "Buy groceries",
        "description": "Get milk, eggs, bread, and vegetables",
        "completed": True,
        "created_at": "2024-08-14T18:30:00"
    },
    "3": {
        "id": "3",
        "title": "Schedule dentist appointment",
        "description": "Call the dentist office to schedule a checkup",
        "completed": False,
        "created_at": "2024-08-16T11:15:00"
    }
}

class ToDoListRequestHandler(BaseHTTPRequestHandler):
    def _set_headers(self, status_code=200):
        self.send_response(status_code)
        self.send_header('Content-type', 'application/json')
        self.end_headers()

    def _send_json_response(self, data, status_code=200):
        self._set_headers(status_code)
        self.wfile.write(json.dumps(data).encode('utf-8'))

    def do_GET(self):
        parsed_path = urllib.parse.urlparse(self.path)
        path = parsed_path.path

        if path == '/':
            endpoints = [
                {"path": "/", "method": "GET", "description": "List all endpoints"},
                {"path": "/tasks", "method": "GET", "description": "List all tasks"},
                {"path": "/tasks", "method": "POST", "description": "Create a new task"},
                {"path": "/tasks/{id}", "method": "GET", "description": "Get a specific task"},
                {"path": "/tasks/{id}", "method": "DELETE", "description": "Delete a specific task"},
                {"path": "/stats", "method": "GET", "description": "Get task statistics"}
            ]
            self._send_json_response({"endpoints": endpoints})
        elif path == '/tasks':
            self._send_json_response({"tasks": list(tasks.values())})
        elif path.startswith('/tasks/'):
            task_id = path.split('/')[-1]
            if task_id in tasks:
                self._send_json_response(tasks[task_id])
            else:
                self._send_json_response({"error": "Task not found"}, 404)
        elif path == '/stats':
            completed = sum(1 for task in tasks.values() if task['completed'])
            stats = {
                "total_tasks": len(tasks),
                "completed_tasks": completed,
                "pending_tasks": len(tasks) - completed
            }
            self._send_json_response(stats)
        else:
            self._send_json_response({"error": "Not Found"}, 404)

    def do_POST(self):
        if self.path == '/tasks':
            content_length = int(self.headers['Content-Length'])
            post_data = self.rfile.read(content_length)
            task_data = json.loads(post_data.decode('utf-8'))

            if 'title' not in task_data:
                self._send_json_response({"error": "Title is required"}, 400)
                return

            task_id = str(uuid4())
            new_task = {
                "id": task_id,
                "title": task_data['title'],
                "description": task_data.get('description', ''),
                "completed": False,
                "created_at": datetime.now().isoformat()
            }
            tasks[task_id] = new_task
            self._send_json_response(new_task, 201)
        else:
            self._send_json_response({"error": "Method Not Allowed"}, 405)

    def do_DELETE(self):
        if self.path.startswith('/tasks/'):
            task_id = self.path.split('/')[-1]
            if task_id in tasks:
                del tasks[task_id]
                self._send_json_response({"message": "Task deleted successfully"})
            else:
                self._send_json_response({"error": "Task not found"}, 404)
        else:
            self._send_json_response({"error": "Method Not Allowed"}, 405)

def run(port=80):
    server_address = ('0.0.0.0', port)
    httpd = HTTPServer(server_address, ToDoListRequestHandler)
    print(f"Server running on port {port}")
    httpd.serve_forever()

if __name__ == '__main__':
    run()