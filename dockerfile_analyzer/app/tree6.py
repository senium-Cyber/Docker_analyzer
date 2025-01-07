from dockerfile_parse import DockerfileParser
import re
import sys
import os

# Updated language table with base image version mappings
language_table = {
    'python': {
        'platforms': {'alpine': ['3.7', '3.9', '3.10']},
        'versions': ['3.7', '3.8', '3.9', '3.10', '3.11', '3.12']
    },
    'node': {
        'platforms': {'alpine': ['14', '16'], 'stretch': []},
        'versions': ['12', '14', '16']
    },
    'java': {
        'platforms': {'alpine': ['8', '11'], 'buster': []},
        'versions': ['8', '11', '17']
    },
    'ruby': {
        'platforms': {'alpine': ['2.7', '3.0']},
        'versions': ['2.7', '3.0']
    },
    'golang': {
        'platforms': {'alpine': ['1.16', '1.17']},
        'versions': ['1.16', '1.17']
    },
    'c': {
        'platforms': {'alpine': ['10', '11']},
        'versions': ['10', '11']
    }
}

def parse_dockerfile(dockerfile_path):
    dfp = DockerfileParser()
    with open(dockerfile_path, 'r') as file:
        dfp.content = file.read()
    return dfp.structure

def classify_layers(dockerfile_ast, dockerfile_dir):
    os_layer = []
    language_layer = []
    dependencies_layer = []
    final_operations_layer = []
    requirements_files = []

    language_detected = False

    for instruction in dockerfile_ast:
        cmd = instruction['instruction'].lower()

        # 处理 FROM 指令，检测语言类型
        if cmd == 'from':
            os_layer.append(instruction)
            base_image = instruction['value'].lower()
            if 'python' in base_image:
                language_layer.append({'instruction': 'LANGUAGE', 'value': 'python'})
                language_detected = True
            elif 'node' in base_image:
                language_layer.append({'instruction': 'LANGUAGE', 'value': 'nodejs'})
                language_detected = True
            elif 'openjdk' in base_image:
                language_layer.append({'instruction': 'LANGUAGE', 'value': 'java'})
                language_detected = True
            elif 'golang' in base_image:
                language_layer.append({'instruction': 'LANGUAGE', 'value': 'golang'})
                language_detected = True
            elif 'ruby' in base_image:
                language_layer.append({'instruction': 'LANGUAGE', 'value': 'ruby'})
                language_detected = True

        # 处理 RUN 指令，检测语言和依赖项
        elif cmd == 'run':
            # 如果语言没有在 FROM 指令中检测到，则尝试从 RUN 指令中检测
            if not language_detected:
                if 'openjdk' in instruction['value'].lower() or 'java' in instruction['value'].lower():
                    language_layer.append({'instruction': 'LANGUAGE', 'value': 'java'})
                    language_detected = True
                elif 'python' in instruction['value'].lower():
                    language_layer.append({'instruction': 'LANGUAGE', 'value': 'python'})
                    language_detected = True
                elif 'node' in instruction['value'].lower():
                    language_layer.append({'instruction': 'LANGUAGE', 'value': 'nodejs'})
                    language_detected = True
                elif 'golang' in instruction['value'].lower():
                    language_layer.append({'instruction': 'LANGUAGE', 'value': 'golang'})
                    language_detected = True
                elif 'ruby' in instruction['value'].lower():
                    language_layer.append({'instruction': 'LANGUAGE', 'value': 'ruby'})
                    language_detected = True
                elif not language_detected and ('gcc' in instruction['value'].lower() or 'make' in instruction['value'].lower() or 'cmake' in instruction['value'].lower()):
                    language_layer.append({'instruction': 'LANGUAGE', 'value': 'c'})
                    language_detected = True

            # 处理 apt-get install 指令，将其归类到 dependencies_layer
            if 'apt-get install' in instruction['value']:
                # 提取要安装的包
                match = re.search(r'apt-get install\s+-y\s+(.+?)(\s+&&.*|$)', instruction['value'])
                if match:
                    packages = match.group(1)
                    # 分离包列表，移除不需要的清理命令
                    package_list = re.split(r'\s+', packages)
                    for pkg in package_list:
                        pkg = pkg.strip()
                        # 忽略清理命令
                        if pkg == 'rm' or pkg == '&&':
                            continue
                        # 如果是语言相关的包，放到语言层
                        if 'python' in pkg or 'pip' in pkg:
                            language_layer.append({'instruction': 'LANGUAGE', 'value': pkg})
                        else:
                            # 否则放到依赖层
                            dependencies_layer.append({'instruction': 'DEPENDENCY', 'value': pkg})
            
            # 处理其他依赖项文件的提取
            elif 'install' in instruction['value']:
                req_file = None  # 确保每次检查时都初始化 req_file

                # 通过正则表达式检测是否有指定依赖文件
                match = re.search(r'-r\s+(\S+)', instruction['value'])
                if match:
                    req_file = match.group(1)
                else:
                    # 检查常见的依赖文件名
                    if 'pip' in instruction['value']:
                        req_file = 'requirements.txt'
                    elif 'npm' in instruction['value']:
                        req_file = 'package.json'
                    elif 'maven' in instruction['value']:
                        req_file = 'pom.xml'
                    elif 'gradle' in instruction['value']:
                        req_file = 'build.gradle'
                    elif 'make' in instruction['value'] or 'gcc' in instruction['value']:
                        req_file = 'Makefile'

                # 如果发现了有效的依赖文件路径，则检查文件是否存在
                if req_file:
                    req_file_path = os.path.join(dockerfile_dir, req_file)
                    if os.path.exists(req_file_path):
                        requirements_files.append(req_file_path)
                    else:
                        print(f"File does not exist: {req_file_path}")
                # 检查是否遇到目录而非文件
                if os.path.isdir(req_file):
                    print(f"Expected file, but found directory: {req_file}")

            # 处理 RUN 指令中的 &&，将其拆分成独立的命令执行
            if '&&' in instruction['value']:
                commands = instruction['value'].split('&&')
                for cmd in commands:
                    cmd = cmd.strip()  # 去除每个命令两边的空格
                    if cmd:  # 确保命令非空
                        # 创建新的 RUN 指令
                        new_instruction = instruction.copy()
                        new_instruction['value'] = cmd
                        dockerfile_ast.append(new_instruction)
            else:
                final_operations_layer.append(instruction)

        # 处理 COPY、ADD、ENV、CMD 等操作指令
        elif cmd in ['copy', 'add', 'env', 'cmd', 'entrypoint', 'workdir']:
            final_operations_layer.append(instruction)

    # 默认语言为 C，防止没有检测到语言
    if not language_detected:
        language_layer.append({'instruction': 'LANGUAGE', 'value': 'c'})

    return os_layer, language_layer, dependencies_layer, final_operations_layer, requirements_files






def normalize_version(version):
    return [int(part) for part in re.split(r'\D+', version) if part.isdigit()]

def compare_versions(version1, version2):
    v1_parts = normalize_version(version1)
    v2_parts = normalize_version(version2)
    
    # Remove trailing zeros
    while v1_parts and v1_parts[-1] == 0:
        v1_parts.pop()
    while v2_parts and v2_parts[-1] == 0:
        v2_parts.pop()
    
    return v1_parts == v2_parts

def get_inferred_version(language, base_image_version, platform):
    if language not in language_table:
        return None
    
    for plat, versions in language_table[language]['platforms'].items():
        if plat == platform:
            for version in versions:
                if version in base_image_version:
                    return version
    return None

# def compare_layers(layer1, layer2):
#     if layer1['instruction'].lower() != layer2['instruction'].lower():
#         return False
#     if layer1['instruction'].lower() == 'from':
#         from1 = layer1['value'].strip()
#         from2 = layer2['value'].strip()
#         base1, version1 = from1.split(':')
#         base2, version2 = from2.split(':')

#         # Compare base image names
#         if base1 != base2:
#             return False

#         # Compare platform tags
#         platform1 = version1.split('-')[-1] if '-' in version1 else ''
#         platform2 = version2.split('-')[-1] if '-' in version2 else ''

#         # Compare versions with inferred versions if applicable
#         inferred_version1 = get_inferred_version(base1, version1, platform1)
#         inferred_version2 = get_inferred_version(base2, version2, platform2)

#         version1 = version1.split('-')[0]
#         version2 = version2.split('-')[0]

#         if inferred_version1 and inferred_version2:
#             return inferred_version1 == inferred_version2
#         elif platform1 != platform2:
#             return False

#         return compare_versions(version1, version2)
#     if 'version' in layer1['value'].lower():
#         version1 = re.search(r'\d+(\.\d+)*', layer1['value'])
#         version2 = re.search(r'\d+(\.\d+)*', layer2['value'])
#         if version1 and version2:
#             return compare_versions(version1.group(), version2.group())
#     return layer1['value'].strip() == layer2['value'].strip()


# def compare_requirements(req_files1, req_files2):
#     reqs1 = set()
#     reqs2 = set()
#     for req_file in req_files1:
#         if os.path.exists(req_file):
#             with open(req_file, 'r') as file:
#                 reqs1.update(file.read().splitlines())
#     for req_file in req_files2:
#         if os.path.exists(req_file):
#             with open(req_file, 'r') as file:
#                 reqs2.update(file.read().splitlines())
    
#     return reqs1.issubset(reqs2) or reqs2.issubset(reqs1)

# def compare_dockerfile_structures(dockerfile1_structure, dockerfile2_structure):
#     os1, lang1, deps1, ops1, reqs1 = dockerfile1_structure
#     os2, lang2, deps2, ops2, reqs2 = dockerfile2_structure
    
#     if not all(compare_layers(os1[i], os2[i]) for i in range(min(len(os1), len(os2)))):
#         return 0
#     if not all(compare_layers(lang1[i], lang2[i]) for i in range(min(len(lang1), len(lang2)))):
#         return 1
#     if not all(compare_layers(deps1[i], deps2[i]) for i in range(min(len(deps1), len(deps2)))) or not compare_requirements(reqs1, reqs2):
#         return 2
#     return 3

# def print_layer(layer, layer_name, requirements_files, output_file, file_number):
#     with open(output_file, 'a') as file:
#         file.write(f"File {file_number} - {layer_name}:\n")
#         if layer_name == "Language Layer":
#             for item in layer:
#                 file.write(f"  {item['value']}\n")
#         else:
#             for item in layer:
#                 file.write(f"  {item['instruction']} {item['value']}\n")
#             if layer_name == "Dependencies Layer" and requirements_files:
#                 file.write("  Requirements Files:\n")
#                 for req_file in requirements_files:
#                     if os.path.exists(req_file):  # Ensure the file exists before opening
#                         with open(req_file, 'r') as req:
#                             file.write(f"    {req_file}:\n")
#                             for line in req:
#                                 file.write(f"      {line}")
#         file.write("\n")

# def main(config_file):
#     # 读取配置文件
#     with open(config_file, 'r') as file:
#         dockerfile_paths = [line.strip() for line in file if line.strip()]
    
#     output_file = "dockerfile_structure_output.txt"
#     comparison_output_file = "dockerfile_comparison_output.txt"
    
#     dockerfile_structures = []
    
#     for idx, path in enumerate(dockerfile_paths, start=1):
#         structure = classify_layers(parse_dockerfile(path), os.path.dirname(path))
#         dockerfile_structures.append((path, structure))
#         os_layer, language_layer, dependencies_layer, final_operations_layer, requirements_files = structure
#         with open(output_file, 'a') as file:
#             file.write(f"Dockerfile {idx}: {path}\n\n")
#         print_layer(os_layer, "OS Layer", requirements_files, output_file, idx)
#         print_layer(language_layer, "Language Layer", requirements_files, output_file, idx)
#         print_layer(dependencies_layer, "Dependencies Layer", requirements_files, output_file, idx)
#         print_layer(final_operations_layer, "Final Operations Layer", requirements_files, output_file, idx)
#         with open(output_file, 'a') as file:
#             file.write("\n")

#     num_files = len(dockerfile_paths)
#     for i in range(num_files):
#         for j in range(i + 1, num_files):
#             path1, structure1 = dockerfile_structures[i]
#             path2, structure2 = dockerfile_structures[j]
#             similarity_level = compare_dockerfile_structures(structure1, structure2)
#             with open(comparison_output_file, 'a') as file:
#                 file.write(f'The maximum similarity level between {path1} and {path2} is: {similarity_level}\n\n')

# if __name__ == '__main__':
#     if len(sys.argv) != 2:
#         print("Usage: python optimize_docker.py <config_file>")
#         sys.exit(1)
    
#     config_file = sys.argv[1]
#     main(config_file)
