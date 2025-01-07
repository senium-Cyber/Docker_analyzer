from flask import Flask, request, jsonify, send_from_directory
from werkzeug.utils import secure_filename
import os
import json
from tree6 import parse_dockerfile, classify_layers
import xml.etree.ElementTree as ET
app = Flask(__name__, static_folder='../static')
UPLOAD_FOLDER = './app/uploads'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# 全局变量，用于存储上传的依赖文件路径
uploaded_dependencies = []
def parse_pom_dependencies(pom_file):
    """解析 pom.xml 文件并提取依赖项"""
    try:
        tree = ET.parse(pom_file)
        root = tree.getroot()
        namespace = {'maven': 'http://maven.apache.org/POM/4.0.0'}
        
        dependencies = []
        for dependency in root.findall('.//maven:dependency', namespace):
            group_id = dependency.find('maven:groupId', namespace)
            artifact_id = dependency.find('maven:artifactId', namespace)
            version = dependency.find('maven:version', namespace)
            
            dep_str = f"{group_id.text}:{artifact_id.text}"
            if version is not None:
                dep_str += f":{version.text}"
            dependencies.append(dep_str)
        
        return dependencies
    except Exception as e:
        raise ValueError(f"Failed to parse pom.xml: {str(e)}")

def filter_dependencies(language, raw_dependencies):
    """
    根据语言类型清理依赖信息，只保留有效内容
    :param language: 语言类型 (e.g., "python", "nodejs")
    :param raw_dependencies: 原始依赖列表
    :return: 清理后的有效依赖
    """
    filtered = []
    if language == "python":
        for dep in raw_dependencies:
            if "==" in dep:  # 依赖格式如 Flask==2.1.1
                filtered.append(dep.strip())
    elif language == "nodejs":
        try:
            # 试图解析为 JSON 格式，并进一步提取 dependencies
            package_json = json.loads("\n".join(raw_dependencies))
            if "dependencies" in package_json:
                for dep, version in package_json["dependencies"].items():
                    filtered.append(f"{dep}@{version}")
        except json.JSONDecodeError:
            pass  # 如果解析失败，忽略此部分
    else:
        if language == "java":
                for dep in raw_dependencies:
                        if dep.endswith('.txt') or dep.endswith('.json') or dep.endswith('.xml'):
                            # 检查文件类型并解析
                            if dep.endswith('pom.xml'):
                                try:
                                    pom_deps = parse_pom_dependencies(dep)
                                    filtered.extend(pom_deps)
                                except ValueError as e:
                                    print(f"Warning: {e}")
                            else:
                                # 忽略无关的依赖文件内容
                                continue
        else :
            for dep in raw_dependencies:
                if dep.strip():
                    filtered.append(dep.strip())
                    
    return filtered


@app.route('/')
def serve_frontend():
    return send_from_directory(app.static_folder, 'index.html')


@app.route('/analyze', methods=['POST'])
def analyze_dockerfile():
    if 'file' not in request.files:
        return jsonify({"error": "No Dockerfile provided"}), 400

    file = request.files['file']
    if file.filename == '':
        return jsonify({"error": "No Dockerfile selected"}), 400

    filename = secure_filename(file.filename)
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    file.save(filepath)

    try:
        # Parse and classify Dockerfile
        dockerfile_ast = parse_dockerfile(filepath)
        os_layer, language_layer, dependencies_layer, final_operations_layer, requirements_files = classify_layers(
            dockerfile_ast, os.path.dirname(filepath)
        )

        # 初始化返回结果
        runtime_dependencies = [item['value'] for item in dependencies_layer]
        result = {
            "OS": [item['value'] for item in os_layer],
            "Language": [item['value'] for item in language_layer],
            "Runtime dependencies": runtime_dependencies.copy(),
            "Missing dependencies": [],
        }

        # 验证上传的依赖文件
        required_files = {
            "python": "requirements.txt",
            "nodejs": "package.json",
            "java": "pom.xml",
        }

        for lang in [item['value'] for item in language_layer]:
            required_file = required_files.get(lang)
            if required_file and required_file not in [os.path.basename(f) for f in uploaded_dependencies]:
                result["Missing dependencies"].append(required_file)

        if result["Missing dependencies"]:
            return jsonify({"error": "Missing runtime dependency files", "missing_files": result["Missing dependencies"]}), 400

        # 打开并解析上传的依赖文件
        for dep_file in uploaded_dependencies:
            try:
                with open(dep_file, 'r') as f:
                    raw_dependencies = f.readlines()
                    # 根据语言清理依赖
                    for lang in [item['value'] for item in language_layer]:
                        filtered_deps = filter_dependencies(lang, raw_dependencies)
                        runtime_dependencies.extend([dep for dep in filtered_deps if dep not in runtime_dependencies])
            except Exception as e:
                return jsonify({"error": f"Error reading dependency file {dep_file}: {str(e)}"}), 500

        # 更新结果中的 Runtime dependencies
        result["Runtime dependencies"] = runtime_dependencies

        return jsonify(result)

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/upload_dependencies', methods=['POST'])
def upload_dependencies():
    if 'dependencies' not in request.files:
        return jsonify({"error": "No dependencies files provided"}), 400

    files = request.files.getlist('dependencies')
    uploaded_files = []

    for file in files:
        if file.filename == '':
            return jsonify({"error": "File name is empty"}), 400

        filename = secure_filename(file.filename)
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(filepath)
        uploaded_files.append(filepath)
        uploaded_dependencies.append(filepath)  # 添加到全局列表

    return jsonify({"message": "Dependencies uploaded successfully", "uploaded_files": uploaded_files}), 200


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5001, debug=True)
