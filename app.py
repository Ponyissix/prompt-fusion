import os
import json
import time
import base64
import io
from PIL import Image
from flask import Flask, render_template, request, jsonify
from volcenginesdkarkruntime import Ark
import concurrent.futures
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)

# Configuration
API_KEY = os.getenv("ARK_API_KEY")
MODEL_ID = os.getenv("MODEL_ID", "doubao-seed-1-6-flash-250828")

client = Ark(
    api_key=API_KEY,
    base_url="https://ark.cn-beijing.volces.com/api/v3"
)

def encode_image(file_storage):
    # Resize image to max 1024x1024 to speed up processing
    img = Image.open(file_storage)
    
    # Convert to RGB if necessary (e.g. for PNGs with alpha)
    if img.mode in ('RGBA', 'P'):
        img = img.convert('RGB')
        
    max_size = 512
    if img.width > max_size or img.height > max_size:
        img.thumbnail((max_size, max_size))
    
    # Save to buffer
    buffer = io.BytesIO()
    img.save(buffer, format="JPEG", quality=85)
    buffer.seek(0)
    
    return "data:image/jpeg;base64," + base64.b64encode(buffer.read()).decode('utf-8')

def analyze_single_image(image_file, selected_aspects, precision_level):
    try:
        start_time = time.time()
        # Create a local client instance for thread safety
        local_client = Ark(
            api_key=API_KEY,
            base_url="https://ark.cn-beijing.volces.com/api/v3"
        )
        
        base64_image = encode_image(image_file)
        encode_time = time.time()
        image_file.seek(0) # Reset pointer

        # Determine detail level
        word_count = "200"
        detail_instruction = "简明扼要"
        if precision_level == "2":
            word_count = "400"
            detail_instruction = "标准详细"
        elif precision_level == "3":
            word_count = "800"
            detail_instruction = "极其详尽，包含所有微小细节"

        aspect_prompts = {
            "风格": "画面整体风格（如：复古胶片、赛博朋克、油画等）。注意：只描述风格，不要描述画面主体内容！",
            "背景": "环境背景细节（地点、天气、氛围）。",
            "构图": "镜头角度、构图方式（如：俯视、三分法、特写）。",
            "人物外貌": "人物的年龄、种族、发型、五官特征。注意：如果画面没有人物，请直接忽略此项！",
            "人物动作": "人物的具体动作、姿态、表情。注意：如果画面没有人物，请直接忽略此项！",
            "穿搭": "服装款式、材质、颜色、配饰。注意：如果画面没有人物，请直接忽略此项！",
            "主体物描述": "画面主要物体（非人物）的详细外观。注意：仅描述主体本身，严禁描述背景或环境！",
            "光影描述": "光线来源、质感、阴影分布。",
            "画面配色": "主色调、配色方案。允许使用“主体”、“背景”等抽象词汇描述颜色分布（如“主体为绿色”），但严禁提及具体物体名称（如“树是绿色”）！",
            "摄像机角度": "仅描述拍摄视角和镜头类型（如：俯视、仰视、平视、鱼眼、长焦、微距等）。严禁描述背景、光影或物体外观！"
        }

        # Filter aspects based on user selection
        selected_instructions = []
        
        # Sort aspects by weight (High priority first)
        # Assuming selected_aspects is a list of dicts: [{'id': 'style', 'weight': 1}, ...]
        # Or if it's legacy format (list of strings), handle that too.
        
        normalized_aspects = []
        if selected_aspects and isinstance(selected_aspects[0], dict):
            # Sort: weight 2 first, then 1
            normalized_aspects = sorted(selected_aspects, key=lambda x: x.get('weight', 1), reverse=True)
        else:
            # Legacy string list
            normalized_aspects = [{'id': a, 'weight': 1} for a in selected_aspects]

        for item in normalized_aspects:
            aspect = item['id']
            weight = item.get('weight', 1)
            
            if aspect in aspect_prompts:
                instruction = aspect_prompts[aspect]
                if weight == 2:
                    # High Priority - STRONGER EMPHASIS
                    selected_instructions.append(f"- 【!!! 核心绝对指令 (Highest Priority) !!!】{aspect}: {instruction} (注意：此维度拥有最高否决权！AI必须无条件服从本维度的描述。如果检测到其他维度（如人物穿搭、背景等）与本维度冲突，必须强制修改其他维度的描述以匹配本维度！例如：若本维度规定主体为绿色，而识别到人物穿红衣，必须改为穿绿衣！)")
                else:
                    # Normal Priority
                    selected_instructions.append(f"- 【参考维度 (Normal Priority)】{aspect}: {instruction}")
        
        aspects_str = "\n".join(selected_instructions)

        prompt = f"""
你是一个专业的AI艺术提示词生成专家。你的任务是分析上传的图片，并根据用户选择的维度生成Stable Diffusion提示词。

用户选择了以下分析维度：
{aspects_str}

请严格遵守以下规则：
1. **严格只分析选中的维度！** 绝对禁止分析未选中的维度。例如：如果用户只选了“画面配色”，你的输出中只能包含“画面配色”这一项，绝对不能出现“风格”、“人物”、“背景”等其他任何维度的描述！
2. 详细程度：{detail_instruction}（约{word_count}字）。
3. 结构化输出。
4. 如果选择了“人物”相关的标签但图中无人物，必须忽略。
5. “风格”标签只描述艺术风格，不描述具体内容。
5. **“画面配色”标签规则**：
   - **允许**：描述“主体”、“背景”、“前景”、“画面”等抽象区域的颜色。例如：“主体呈现深绿色”、“背景为高饱和粉紫色”。
   - **禁止**：描述具体的物体、人物或材质名称。例如：**绝对不能说**“绿色的树”、“红色的裙子”、“蓝色的天空”。请将具体物体替换为“主体”或“背景”等抽象代词。
6. **输出格式严格如下**：
   - 只能输出用户选择的维度！
   - 绝对禁止输出用户未选择的维度！如果用户只选了“画面配色”，就只能输出“画面配色”，绝对不能出现“风格”、“人物”等其他内容！
7. **权重冲突处理原则**：
   - AI必须优先满足【核心维度】的描述。
   - 如果【核心维度】（如配色）与【参考维度】（如人物穿搭）发生冲突（例如：配色要求主体为绿色，但图中人物穿红衣），**必须修改参考维度的描述以适配核心维度**（即输出“人物穿着绿色衣服”），并在分析中注明“（已根据核心配色权重修正）”。
   - **强制执行**：请检查每一个维度的描述，确保没有任何一个维度违背了【核心维度】的设定。即使这会通过修改画面内容（如改变衣服颜色）来实现，也必须执行。


[Chinese Analysis]
(这里逐条列出中文分析，格式：- 维度名：描述...)

[English Prompt]
(这里将上述所有维度的关键视觉信息融合成一个完整的英文提示词，使用逗号分隔，适合Stable Diffusion/Midjourney使用)

请直接输出分析结果，不要包含寒暄语。
"""
        
        response = local_client.chat.completions.create(
            model=MODEL_ID,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": base64_image}}
                    ]
                }
            ],
            extra_body={
                "thinking": {"type": "disabled"}
            }
        )
        end_time = time.time()
        print(f"DEBUG: API call took {end_time - encode_time:.2f}s for {image_file.filename}")
        print(f"DEBUG: Total processing time: {end_time - start_time:.2f}s for {image_file.filename}")
        return response.choices[0].message.content
    except Exception as e:
        print(f"Error analyzing image {image_file.filename}: {e}")
        return f"Error: {str(e)}"

def merge_prompts(analyses, precision_level):
    # If only one analysis, just format it
    combined_analysis = "\n\n---\n\n".join(analyses)
    
    detail_req = "standard detail"
    if precision_level == "3":
        detail_req = "extremely detailed"

    system_prompt = f"""
你是一个专业的Stable Diffusion和Midjourney提示词生成助手。
你的任务是将以下的一段或多段图片分析文本，融合成一组高质量的提示词。

输入内容：
{combined_analysis}

任务要求：
1. **中文结构化解析**：
   - 将所有图片的特征融合，总结出一个连贯的中文画面描述。
   - **必须融合成单张画面的描述**！严禁使用“在另一场景中”、“另一幅画面”等分割画面的词汇。如果输入的多张图片风格或内容冲突，你必须发挥创意，将它们强行融合到一个统一的场景中（例如：将A图的人物放入B图的背景，或者让A图的风格与B图的配色结合）。
   - 保持{detail_req}级别的详细程度。
   - 格式：
     [Chinese]
     (这里写中文描述)

2. **英文提示词 (SD/MJ)**：
   - 将上面的中文描述精准翻译成英文提示词。
   - 使用逗号分隔的关键词或短语格式。
   - 包含风格、主体、环境、光照、构图等关键词。
   - 确保英文内容与中文描述完全一致！不要遗漏细节。
   - 格式：
     [English]
     (Here write the English prompt)

**重要约束**：
- 必须严格包含 [Chinese] 和 [English] 两个标签。
- [Chinese] 部分只准包含中文。
- [English] 部分只准包含英文。
- 不要有任何其他开场白或结束语。
"""

    response = client.chat.completions.create(
        model=MODEL_ID,
        messages=[
            {"role": "user", "content": system_prompt}
        ],
        extra_body={
            "thinking": {"type": "disabled"}
        }
    )
    return response.choices[0].message.content

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/generate', methods=['POST'])
def generate():
    if 'images' not in request.files:
        return jsonify({'error': 'No images uploaded'}), 400
    
    images = request.files.getlist('images')
    options_str = request.form.get('options')
    precision = request.form.get('precision', '2')
    
    if not options_str:
        return jsonify({'error': 'No options provided'}), 400

    try:
        options_map = json.loads(options_str)
    except:
        return jsonify({'error': 'Invalid options format'}), 400

    # Parallel processing
    individual_prompts = [None] * len(images)
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        future_to_idx = {}
        for idx, image in enumerate(images):
            # keys might be strings "0", "1"...
            aspects = options_map.get(str(idx), [])
            future = executor.submit(analyze_single_image, image, aspects, precision)
            future_to_idx[future] = idx
            
        for future in concurrent.futures.as_completed(future_to_idx):
            idx = future_to_idx[future]
            try:
                result = future.result()
                individual_prompts[idx] = result
            except Exception as e:
                individual_prompts[idx] = f"Error: {str(e)}"

    # Merge prompts or use single result
    try:
        if len(individual_prompts) == 1 and individual_prompts[0] and "Error" not in individual_prompts[0]:
            # Optimization: Skip merge step for single image
            raw_result = individual_prompts[0]
            # Convert tags to match final format
            final_prompt = raw_result.replace("[Chinese Analysis]", "[Chinese]").replace("[English Prompt]", "[English]")
        else:
            final_prompt = merge_prompts(individual_prompts, precision)
    except Exception as e:
        final_prompt = f"Error merging prompts: {str(e)}"

    return jsonify({
        'final_prompt': final_prompt,
        'individual_prompts': individual_prompts
    })

if __name__ == '__main__':
    app.run(debug=True, port=5000)
