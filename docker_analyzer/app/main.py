from flask import Flask, request, jsonify, send_from_directory
from werkzeug.utils import secure_filename
import os
import json
from app import process_dockerfile, extract_layers  # 引入函数
import shutil

app = Flask(__name__, static_folder='../static')
UPLOAD_FOLDER = './app/uploads'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

def get_files_from_folder(folder_path):
    """递归获取文件夹中的所有文件"""
    file_list = []
    for root, _, files in os.walk(folder_path):
        for file in files:
            file_list.append(os.path.join(root, file))
    return file_list

@app.route('/')
def serve_frontend():
    return send_from_directory(app.static_folder, 'index.html')

@app.route('/analyze', methods=['POST'])
def analyze_dockerfile():
    try:
        # 检查是否有文件上传
        if 'folder_files' not in request.files:
            return jsonify({"error": "No files uploaded"}), 400

        # 创建临时文件夹存储上传的文件
        folder_path = os.path.join(app.config['UPLOAD_FOLDER'], 'temp_folder')
        os.makedirs(folder_path, exist_ok=True)

        # 保存所有上传的文件
        files = request.files.getlist('folder_files')
        for file in files:
            relative_path = file.filename  # 获取相对路径
            full_path = os.path.join(folder_path, relative_path)
            os.makedirs(os.path.dirname(full_path), exist_ok=True)  # 创建子目录
            file.save(full_path)

        # 查找 Dockerfile
        all_files = get_files_from_folder(folder_path)
        dockerfile_path = next((f for f in all_files if os.path.basename(f).lower() == 'dockerfile'), None)
        if not dockerfile_path:
            return jsonify({"error": "No Dockerfile found in the uploaded folder"}), 400

        # 调用 process_dockerfile 分析 Dockerfile
        dockerfile_ast = process_dockerfile(dockerfile_path)
        if dockerfile_ast is None:
            return jsonify({"error": "Failed to parse the Dockerfile"}), 400

        # 调用 extract_layers 提取层次信息
        os_layer, language_layer, dependencies_layer = extract_layers(dockerfile_ast)

        # 组装结果
        result = {
            "OS Layer": os_layer,
            "Language Layer": language_layer,
            "Dependencies Layer": dependencies_layer,
        }

        # 清理临时文件夹
        shutil.rmtree(folder_path)
        return jsonify(result)

    except Exception as e:

        shutil.rmtree(folder_path, ignore_errors=True)
        return jsonify({"error": str(e)}), 500


if __name__ == '__main__':
    app.run()
