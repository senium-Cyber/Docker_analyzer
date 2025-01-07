from flask import Flask, request, jsonify, send_from_directory
from werkzeug.utils import secure_filename
import os
import json
from tree6 import parse_dockerfile, classify_layers
import xml.etree.ElementTree as ET
import shutil
app = Flask(__name__, static_folder='../static')
UPLOAD_FOLDER = './app/uploads'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

def merge_dependencies(dependencies):
    """合并依赖项，保留相同包名的最新版本"""
    dep_dict = {}
    for dep in dependencies:
        if "==" in dep:
            name, version = dep.split("==")
        elif ":" in dep:
            name, version = dep.split(":")
        elif "@" in dep:
            name, version = dep.split("@")
        else:
            name, version = dep, None

        if name in dep_dict:
            if version and (dep_dict[name] is None or version > dep_dict[name]):
                dep_dict[name] = version
        else:
            dep_dict[name] = version

    return [f"{name}=={version}" if version else name for name, version in dep_dict.items()]

def filter_dependencies(language, raw_dependencies):
    """根据语言类型清理依赖信息"""
    filtered = []
    if language == "python":
        for dep in raw_dependencies:
            if "==" in dep:
                filtered.append(dep.strip())
    elif language == "nodejs":
        try:
            package_json = json.loads("\n".join(raw_dependencies))
            if "dependencies" in package_json:
                for dep, version in package_json["dependencies"].items():
                    filtered.append(f"{dep}=={version}")
        except json.JSONDecodeError:
            pass
    elif language == "java":
        for dep in raw_dependencies:
            if dep.endswith('pom.xml'):
                try:
                    pom_deps = parse_pom_dependencies(dep)
                    filtered.extend(pom_deps)
                except ValueError as e:
                    print(f"Warning: {e}")
    else:
        for dep in raw_dependencies:
            if dep.strip():
                filtered.append(dep.strip())
    return filtered

def parse_pom_dependencies(pom_file):
    """解析 pom.xml 文件并提取依赖项"""
    try:
        tree = ET.parse(pom_file)
        root = tree.getroot()
        # Maven POM 文件的命名空间
        namespace = {'maven': 'http://maven.apache.org/POM/4.0.0'}
        
        dependencies = []
        # 打印 XML 内容来调试
        print(ET.tostring(root, encoding='unicode'))
        
        # 解析所有 <maven:dependency> 元素
        for dependency in root.findall('.//maven:dependency', namespace):
            group_id = dependency.find('maven:groupId', namespace)
            artifact_id = dependency.find('maven:artifactId', namespace)
            version = dependency.find('maven:version', namespace)
            
            if group_id is not None and artifact_id is not None:
                dep_str = f"{group_id.text}:{artifact_id.text}"
                if version is not None:
                    dep_str += f":{version.text}"
                dependencies.append(dep_str)
        
        return dependencies
    except Exception as e:
        raise ValueError(f"Failed to parse pom.xml: {str(e)}")




# def filter_dependencies(language, raw_dependencies):
#     """根据语言类型清理依赖信息"""
#     filtered = []
#     if language == "python":
#         for dep in raw_dependencies:
#             if "==" in dep:
#                 filtered.append(dep.strip())
#     elif language == "nodejs":
#         try:
#             package_json = json.loads("\n".join(raw_dependencies))
#             if "dependencies" in package_json:
#                 for dep, version in package_json["dependencies"].items():
#                     filtered.append(f"{dep}@{version}")
#         except json.JSONDecodeError:
#             pass
#     elif language == "java":
#         for dep in raw_dependencies:
#             if dep.endswith('.xml') and dep.endswith('pom.xml'):
#                 try:
#                     pom_deps = parse_pom_dependencies(dep)
#                     filtered.extend(pom_deps)
#                 except ValueError as e:
#                     print(f"Warning: {e}")
#     else:
#         for dep in raw_dependencies:
#             if dep.strip():
#                 filtered.append(dep.strip())
#     return filtered


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

        # 解析 Dockerfile
        dockerfile_ast = parse_dockerfile(dockerfile_path)
        os_layer, language_layer, dependencies_layer, final_operations_layer, _ = classify_layers(
            dockerfile_ast, os.path.dirname(dockerfile_path)
        )

        # 初始化结果
        runtime_dependencies = [item['value'] for item in dependencies_layer]
        result = {
            "OS": [item['value'] for item in os_layer],
            "Language": [item['value'] for item in language_layer],
            "Runtime dependencies": runtime_dependencies.copy(),
            "Missing dependencies": [],
        }

        # 验证依赖文件是否存在
        required_files = {
            "python": "requirements.txt",
            "nodejs": "package.json",
            "java": "pom.xml",
        }
        for lang in [item['value'] for item in language_layer]:
            required_file = required_files.get(lang)
            if required_file:
                dependency_file = next((f for f in all_files if os.path.basename(f) == required_file), None)
                if dependency_file:
                    try:
                        with open(dependency_file, 'r') as f:
                            raw_dependencies = f.readlines()
                            filtered_deps = filter_dependencies(lang, raw_dependencies)
                            runtime_dependencies.extend(filtered_deps)
                    except Exception as e:
                        return jsonify({"error": f"Error reading dependency file {dependency_file}: {str(e)}"}), 500

        # 合并依赖项
        runtime_dependencies = merge_dependencies(runtime_dependencies)

        # 如果缺少依赖文件
        if result["Missing dependencies"]:
            return jsonify({"error": "Missing runtime dependency files", "missing_files": result["Missing dependencies"]}), 400

        # 解析并清理依赖
        for file in all_files:
            if os.path.basename(file) in required_files.values():
                try:
                    with open(file, 'r') as f:
                        raw_dependencies = f.readlines()
                        for lang in [item['value'] for item in language_layer]:
                            filtered_deps = filter_dependencies(lang, raw_dependencies)
                            runtime_dependencies.extend([dep for dep in filtered_deps if dep not in runtime_dependencies])
                except Exception as e:
                    return jsonify({"error": f"Error reading dependency file {file}: {str(e)}"}), 500

        # 更新结果
        result["Runtime dependencies"] = runtime_dependencies
        shutil.rmtree(folder_path)
        return jsonify(result)

    except Exception as e:
        shutil.rmtree(folder_path, ignore_errors=True)
        return jsonify({"error": str(e)}), 500


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5001, debug=True)
