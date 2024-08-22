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
            'ecr_image_uri': None,
            'instance_prefix': None,
            'instances': [],
            'instance_counter': 0,
            'total_cost': 0.0,
            'env_vars': {}
        }

    def save_state(self):
        with open(self.filename, 'w') as f:
            json.dump(self.state, f, indent=2)

    def update_ecr_uri_and_prefix(self, ecr_image_uri: str, instance_prefix: str):
        self.state['ecr_image_uri'] = ecr_image_uri
        self.state['instance_prefix'] = instance_prefix
        self.save_state()

    def add_instance(self, instance: Dict[str, Any]):
        self.state['instances'].append(instance)
        self.state['instance_counter'] += 1
        self.save_state()

    def remove_instance(self, instance_id: str) -> bool:
        initial_length = len(self.state['instances'])
        instance = next((i for i in self.state['instances'] if i['id'] == instance_id), None)
        if instance:
            self.state['instances'] = [i for i in self.state['instances'] if i['id'] != instance_id]
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

    def get_instances(self) -> List[Dict[str, Any]]:
        return self.state['instances']

    def get_ecr_image_uri(self) -> str:
        return self.state['ecr_image_uri']

    def get_instance_prefix(self) -> str:
        return self.state['instance_prefix']

    def get_instance_counter(self) -> int:
        return self.state['instance_counter']

    def get_total_cost(self) -> float:
        return self.state['total_cost']
    
    def save_env_vars(self, env_vars: Dict[str, str]):
        self.state['env_vars'] = env_vars
        self.save_state()

    def get_env_vars(self) -> Dict[str, str]:
        return self.state['env_vars']