import json
import os
from typing import Dict, List, Any
from datetime import datetime

class StateManager:
    def __init__(self, filename: str = 'instance_state.json'):
        self.filename = filename
        self.state: Dict[str, Any] = self.load_state()

    def load_state(self) -> Dict[str, Any]:
        if os.path.exists(self.filename):
            with open(self.filename, 'r') as f:
                return json.load(f)
        return {
            'apps': {},
            'total_cost': 0.0
        }

    def save_state(self):
        with open(self.filename, 'w') as f:
            json.dump(self.state, f, indent=2)

    def add_app(self, app_name: str, ecr_image_uri: str):
        if app_name not in self.state['apps']:
            self.state['apps'][app_name] = {
                'ecr_image_uri': ecr_image_uri,
                'instances': [],
                'instance_counter': 0
            }
            self.save_state()
            return True
        return False

    def update_ecr_uri(self, app_name: str, ecr_image_uri: str):
        if app_name in self.state['apps']:
            self.state['apps'][app_name]['ecr_image_uri'] = ecr_image_uri
            self.save_state()
            return True
        return False

    def add_instance(self, app_name: str, instance: Dict[str, Any]):
        if app_name in self.state['apps']:
            self.state['apps'][app_name]['instances'].append(instance)
            self.state['apps'][app_name]['instance_counter'] += 1
            self.save_state()
            return True
        return False

    def remove_instance(self, app_name: str, instance_id: str) -> bool:
        if app_name in self.state['apps']:
            app = self.state['apps'][app_name]
            instance = next((i for i in app['instances'] if i['id'] == instance_id), None)
            if instance:
                app['instances'] = [i for i in app['instances'] if i['id'] != instance_id]
                self.calculate_and_add_cost(instance)
                self.save_state()
                return True
        return False

    def calculate_and_add_cost(self, instance: Dict[str, Any]):
        start_time = datetime.fromtimestamp(instance['time_now'])
        end_time = datetime.now()
        duration_hours = (end_time - start_time).total_seconds() / 3600
        cost = duration_hours * instance['spot_price']
        self.state['total_cost'] += cost
        print(f"Instance {instance['id']} ran for {duration_hours:.2f} hours at ${instance['spot_price']}/hour. Cost: ${cost:.4f}")
        print(f"Total project cost so far: ${self.state['total_cost']:.4f}")

    def get_apps(self) -> Dict[str, Dict[str, Any]]:
        return self.state['apps']

    def get_app(self, app_name: str) -> Dict[str, Any]:
        return self.state['apps'].get(app_name, {})

    def get_instances(self, app_name: str) -> List[Dict[str, Any]]:
        return self.state['apps'].get(app_name, {}).get('instances', [])

    def get_ecr_image_uri(self, app_name: str) -> str:
        return self.state['apps'].get(app_name, {}).get('ecr_image_uri')

    def get_instance_counter(self, app_name: str) -> int:
        return self.state['apps'].get(app_name, {}).get('instance_counter', 0)

    def get_total_cost(self) -> float:
        return self.state['total_cost']
    
    def save_env_vars(self, app_name: str, env_vars: Dict[str, str]):
        if app_name not in self.state['apps']:
            raise ValueError(f"App '{app_name}' not found")
        self.state['apps'][app_name]['env_vars'] = env_vars
        self.save_state()

    def get_env_vars(self, app_name: str) -> Dict[str, str]:
        if app_name not in self.state['apps']:
            raise ValueError(f"App '{app_name}' not found")
        return self.state['apps'][app_name].get('env_vars', {})

    def add_app(self, app_name: str, ecr_image_uri: str):
        if app_name not in self.state['apps']:
            self.state['apps'][app_name] = {
                'ecr_image_uri': ecr_image_uri,
                'instances': [],
                'instance_counter': 0,
                'env_vars': {}
            }
            self.save_state()
            return True
        return False