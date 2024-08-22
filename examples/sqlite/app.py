import sqlite3
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from flask import Flask, jsonify, request, send_file
import io
import base64

class DataAnalysisTool:
    def __init__(self, db_path):
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.cursor = self.conn.cursor()

    def load_data(self, query):
        return pd.read_sql_query(query, self.conn)

    def visualize_data(self, df, data_type):
        plt.figure(figsize=(12, 6))
        plt.plot(df['timestamp'], df[data_type])
        plt.title(f'{data_type.capitalize()} on {df["timestamp"].iloc[0].date()}')
        plt.xlabel('Time')
        plt.ylabel(data_type.capitalize())
        plt.xticks(rotation=45)
        plt.tight_layout()
        img_buf = io.BytesIO()
        plt.savefig(img_buf, format='png')
        img_buf.seek(0)
        plt.close()
        return base64.b64encode(img_buf.getvalue()).decode()

app = Flask(__name__)
tool = DataAnalysisTool('sensor_data.db')

@app.route('/')
def index():
    return send_file('index.html')

@app.route('/api/query', methods=['POST'])
def query_data():
    query = request.json['query']
    df = tool.load_data(query)
    return jsonify(df.to_dict(orient='records'))

@app.route('/api/visualize', methods=['POST'])
def visualize_data():
    sensor_id = request.json['sensor_id']
    date = request.json['date']
    data_type = request.json['data_type']
    
    query = f"""
    SELECT timestamp, {data_type}
    FROM sensor_data
    WHERE sensor_id = {sensor_id}
        AND date(timestamp) = '{date}'
    ORDER BY timestamp
    """
    
    df = tool.load_data(query)
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    
    img_base64 = tool.visualize_data(df, data_type)
    return jsonify({'image': img_base64})

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=80)