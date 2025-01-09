import re
import os
import sys
import json
import tqdm
import subprocess
import dockerfile

# Helper function to process embedded bash
def parse_within(bash_str):
    parsed = {'type': 'UNKNOWN', 'children': []}  # Start with nothing
    try:
        step1 = subprocess.check_output(
            '/build/app',
            stderr=subprocess.DEVNULL,
            input=bash_str.encode('utf-8')
        )
        step2 = subprocess.check_output(
            ['jq', '-c', '--from-file', '/filters/filter-1.jq'],
            stderr=subprocess.DEVNULL,
            input=step1
        )
        step3 = subprocess.check_output(
            ['jq', '-c', '--from-file', '/filters/filter-2.jq'],
            stderr=subprocess.DEVNULL,
            input=step2
        )
        parsed = json.loads(step3.decode('utf-8'))
    except Exception:
        return {'type': 'UNKNOWN', 'children': []}
    return parsed

# Function to process Dockerfile and generate AST
def process_dockerfile(dockerfile_path):
    VALID_DIRECTIVES = [
        'from', 'run', 'cmd', 'label', 'maintainer', 'expose', 'env', 'add', 'copy',
        'entrypoint', 'volume', 'user', 'workdir', 'arg', 'onbuild', 'stopsignal', 'healthcheck', 'shell'
    ]

    try:
        with open(dockerfile_path) as dfh:
            content = dfh.read()
            print(f"Dockerfile content:\n{content}")  # Debugging line
            parsed = dockerfile.parse_string(content)
            print(f"Parsed Dockerfile: {parsed}")  # Debugging line

        dockerfile_ast = {
            'type': 'DOCKER-FILE',
            'children': []
        }

        for directive in parsed:
            if directive.cmd.lower() not in VALID_DIRECTIVES:
                raise Exception(f'Found invalid directive {directive.cmd}')

            if directive.cmd.lower() == 'run':
                dockerfile_ast['children'].append({
                    'type': 'DOCKER-RUN',
                    'children': [{
                        'type': 'MAYBE-BASH',
                        'value': directive.value[0],
                        'children': []
                    }]
                })
            elif directive.cmd.lower() == 'from':
                from_node = {
                    'type': 'DOCKER-FROM',
                    'children': []
                }

                value = directive.value[0]
                name = value.split('/')[-1].strip() if '/' in value else value
                name = name.split(':')[0].strip() if ':' in name else name

                from_node['children'].append({
                    'type': 'DOCKER-IMAGE-NAME',
                    'value': name,
                    'children': []
                })

                if '/' in value:
                    from_node['children'].append({
                        'type': 'DOCKER-IMAGE-REPO',
                        'value': value.split('/')[0].strip(),
                        'children': []
                    })

                if ':' in value:
                    from_node['children'].append({
                        'type': 'DOCKER-IMAGE-TAG',
                        'value': value.split(':')[-1].strip(),
                        'children': []
                    })

                dockerfile_ast['children'].append(from_node)

        print(f"Dockerfile AST: {dockerfile_ast}")  # Debugging line
        return dockerfile_ast

    except Exception as e:
        print(f"Error processing {dockerfile_path}: {str(e)}")
        return None


# Tree traversal to extract OS, Language, and Dependencies
# Tree traversal to extract OS, Language, and Dependencies

def extract_layers(ast):
    os_list = []
    language_list = []
    dependencies_list = []
    language_detected = False

    def traverse(node):
        nonlocal language_detected

        # Extract OS from 'DOCKER-FROM'
        if node['type'] == 'DOCKER-FROM':
            for child in node.get('children', []):
                if child['type'] == 'DOCKER-IMAGE-NAME':
                    base_image = child['value'].lower()
                    os_detected = False

                    # Detect OS based on base image name
                    if 'alpine' in base_image:
                        os_list.append('alpine')
                        os_detected = True
                    elif 'ubuntu' in base_image:
                        os_list.append('ubuntu')
                        os_detected = True
                    elif 'debian' in base_image:
                        os_list.append('debian')
                        os_detected = True

                    # Detect language based on base image
                    if 'python' in base_image:
                        language_list.append('python')
                        language_detected = True
                    elif 'node' in base_image:
                        language_list.append('nodejs')
                        language_detected = True
                    elif 'openjdk' in base_image:
                        language_list.append('java')
                        language_detected = True
                    elif 'golang' in base_image:
                        language_list.append('golang')
                        language_detected = True
                    elif 'ruby' in base_image:
                        language_list.append('ruby')
                        language_detected = True
                    elif 'gcc' in base_image or 'alpine' in base_image:
                        language_list.append('c')
                        language_detected = True

        # Extract dependencies from 'DOCKER-RUN'
        elif node['type'] == 'DOCKER-RUN':
            run_command = node['children'][0]['value'].lower()

            # Detect language from run command if not already detected
            if not language_detected:
                if 'openjdk' in run_command or 'java' in run_command:
                    language_list.append('java')
                    language_detected = True
                elif 'python' in run_command:
                    language_list.append('python')
                    language_detected = True
                elif 'node' in run_command:
                    language_list.append('nodejs')
                    language_detected = True
                elif 'golang' in run_command:
                    language_list.append('golang')
                    language_detected = True
                elif 'ruby' in run_command:
                    language_list.append('ruby')
                    language_detected = True
                elif 'gcc' in run_command or 'make' in run_command or 'cmake' in run_command:
                    language_list.append('c')
                    language_detected = True

            # Extract dependencies from installation commands
            if 'apt-get install' in run_command:
                dependencies = re.findall(r'apt-get install\s+-y\s+([\w\s\-\.]+)', run_command)
                dependencies_list.extend(dependencies)
            elif 'pip install' in run_command or 'pip3 install' in run_command:
                dependencies = re.findall(r'pip(?:3)? install\s+([\w\s\-\.]+)', run_command)
                dependencies_list.extend(dependencies)
            elif 'npm install' in run_command:
                dependencies = re.findall(r'npm install\s+([\w\s\-\.]+)', run_command)
                dependencies_list.extend(dependencies)
            elif 'gem install' in run_command:
                dependencies = re.findall(r'gem install\s+([\w\s\-\.]+)', run_command)
                dependencies_list.extend(dependencies)

        # Extract language from 'DOCKER-ENV'
        elif node['type'] == 'DOCKER-ENV':
            env_value = node.get('value', '').lower()
            if 'python' in env_value:
                language_list.append('python')
                language_detected = True
            elif 'java' in env_value:
                language_list.append('java')
                language_detected = True
            elif 'node' in env_value:
                language_list.append('nodejs')
                language_detected = True
            elif 'golang' in env_value:
                language_list.append('golang')
                language_detected = True
            elif 'ruby' in env_value:
                language_list.append('ruby')
                language_detected = True
            elif 'c' in env_value:
                language_list.append('c')
                language_detected = True

        # Recursively traverse child nodes
        for child in node.get('children', []):
            traverse(child)

    traverse(ast)

    # If no language was detected, default to 'c'
    if not language_detected:
        language_list.append('c')

    return os_list, language_list, dependencies_list



# Main function to process Dockerfiles sequentially
def process(line):
    print(f"Processing {line}")  # Debugging line
    ast = process_dockerfile(line.strip())
    if ast:
        os_list, language_list, dependencies_list = extract_layers(ast)
        print(f"AST: {ast}")  # Debugging line
        return {
        'ast': ast,
        'os': os_list,
        'language': language_list,
        'dependencies': dependencies_list
    }
    return None

#dockerfile_paths = ['/home/comp/csxtchen/group/dockerfile_analyzer/binnacle-icse2020/datasets/3-phase-3-dockerfile-asts/generate/Dockerfile']  # Hardcoded paths for testing

# # Process Dockerfiles sequentially (single thread)
# with open('dockerfile_ast.txt', mode='w') as ast_file, \
#      open('dockerfile_summary.txt', mode='w') as summary_file:
    
#     for line in tqdm.tqdm(dockerfile_paths, total=len(dockerfile_paths), desc="Processing"):
#         result = process(line)
#         if result is None:
#             continue
#         ast_file.write('{}\n'.format(json.dumps(result['ast'])))
#         summary = {
#             'os': result['os'],
#             'language': result['language'],
#             'dependencies': result['dependencies']
#         }
#     summary_file.write('{}\n'.format(json.dumps(summary)))
