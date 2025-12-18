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

client = None
if API_KEY:
    try:
        client = Ark(
            api_key=API_KEY,
            base_url="https://ark.cn-beijing.volces.com/api/v3",
            timeout=900
        )
    except Exception as e:
        print(f"Warning: Failed to initialize Ark client: {e}")
else:
    print("Warning: ARK_API_KEY environment variable is not set. Application will start but generation will fail.")

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
            base_url="https://ark.cn-beijing.volces.com/api/v3",
            timeout=900
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
            word_count = "1200"
            detail_instruction = "极度详尽，显微镜级别的细节描述，包括材质纹理、光线微尘、背景微小物体等所有可见元素"

        aspect_prompts = {
            "风格": "画面整体风格（如：复古胶片、赛博朋克、油画等）。注意：只描述风格，不要描述画面主体内容！",
            "背景": "环境背景细节（地点、天气、氛围）。",
            "构图": "镜头角度、构图方式（如：俯视、三分法、特写）。注意：仅描述构图形式，严禁描述画面中具体的物体或人物！",
            "人物外貌": "人物的年龄、种族、发型、五官特征。注意：如果画面没有人物，请输出'无人物'或'None'。",
            "人物动作": "人物的具体动作、姿态、表情。注意：如果画面没有人物，请输出'无人物'或'None'。严禁描述服装或外貌！",
            "穿搭": "服装款式、材质、颜色、配饰。注意：如果画面没有人物，请输出'无人物'或'None'。",
            "主体物描述": "画面主要物体（非人物）的详细外观。注意：仅描述主体本身，严禁描述背景或环境！",
            "光影描述": "光线来源、质感、阴影分布。",
            "画面配色": "主色调、配色方案。允许使用“主体”、“背景”等抽象词汇描述颜色分布（如“主体为绿色”），但严禁提及具体物体名称（如“树是绿色”）！",
            "摄像机角度": "仅描述拍摄视角和镜头类型（如：俯视、仰视、平视、鱼眼、长焦、微距等）。严禁描述背景、光影或物体外观！",
            "文字/水印": "识别并转录画面中的所有可见文字、水印、LOGO信息。若无文字，请注明无。注意：如果用户没有选择此标签，绝对不要在其他标签（如背景、主体）中提及文字或水印内容！"
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
                if str(weight) == '2':
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
1. **严格只分析选中的维度！** 绝对禁止分析未选中的维度。
   - **特别注意**：如果用户没有选择“文字/水印”标签，**绝对禁止**在任何地方（包括背景、主体描述中）提及画面中的文字、水印、日期、时间或LOGO信息！必须假装这些文字不存在。
2. **必须输出所有选中维度**：
   - 如果某维度不适用（例如选了“人物”但图中无人物），请明确输出该维度名称，并标注“无人物”或“不适用”。
3. 详细程度：{detail_instruction}（约{word_count}字）。
4. **“画面配色”标签规则**：
   - **允许**：描述“主体”、“背景”、“前景”、“画面”等抽象区域的颜色。
   - **禁止**：描述具体的物体、人物或材质名称。请将具体物体替换为“主体”或“背景”等抽象代词。
5. **输出格式严格如下**：
   - 只能输出用户选择的维度！
   - 绝对禁止输出用户未选择的维度！
6. **权重冲突处理原则**：
   - AI必须优先满足【核心维度】的描述。
   - 如果【核心维度】与【参考维度】发生冲突，**必须修改参考维度的描述以适配核心维度**。

7. **关于“无人物外貌描述”**：
   - 如果识别到人物（哪怕只是局部），必须直接描述特征。
   - 只有完全没有人类时，才能说“无人物”。
   - **严禁输出内部推理过程或自我纠正的内容！**（例如：“无人物（因为...）”这种格式是绝对禁止的）。直接输出最终结论。

[Chinese Analysis]
(这里逐条列出中文分析，格式：- 维度名：描述...)

请直接输出分析结果，**不要输出任何思考过程、自我纠正或寒暄语**。
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
        import traceback
        traceback.print_exc()
        return f"Error: {str(e)}"

def merge_prompts(analyses, precision_level, use_thinking=True):
    if not client:
        return "Error: Ark client is not initialized. Please check ARK_API_KEY."

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
   - **必须融合成单张画面的描述**！严禁使用“在另一场景中”、“另一幅画面”等分割画面的词汇。
   - **严厉的内容审查**：请仔细检查每一条描述。如果某项描述包含了不属于该维度的内容（例如“人物动作”里描述了“穿着蓝色外套”），**必须立刻删除不相关内容**！只保留纯粹的动作描述。
   - 保持{detail_req}级别的详细程度。
   - 格式：
     [Chinese]
     (这里写中文描述)

**重要约束**：
- 只输出 [Chinese] 部分。
- 不要有任何其他开场白或结束语。
- **绝对禁止输出任何备注、解释或说明！**（例如：“注：已删除...”、“因为...”）。
- 如果遇到冲突，请直接默默修正，**不要**告诉用户你做了修正。
- 最终输出必须纯粹是画面描述，不包含任何元数据或编辑注释。
"""

    extra_body = {}
    if use_thinking:
        extra_body["thinking"] = {"type": "enabled"}
    else:
        extra_body["thinking"] = {"type": "disabled"}

    response = client.chat.completions.create(
        model=MODEL_ID,
        messages=[
            {"role": "user", "content": system_prompt}
        ],
        extra_body=extra_body
    )
    return response.choices[0].message.content

def generate_fused_prompt_directly(images, options_map, precision_level, use_thinking=True):
    try:
        if not API_KEY:
             return "Error: ARK_API_KEY environment variable is missing. Please configure it in your deployment settings."

        start_time = time.time()
        # Create a local client instance for thread safety
        local_client = Ark(
            api_key=API_KEY,
            base_url="https://ark.cn-beijing.volces.com/api/v3",
            timeout=900
        )
        
        # Determine detail level
        word_count = "200"
        detail_instruction = "简明扼要"
        if precision_level == "2":
            word_count = "400"
            detail_instruction = "标准详细"
        elif precision_level == "3":
            word_count = "1200"
            detail_instruction = "极度详尽，显微镜级别的细节描述，包括材质纹理、光线微尘、背景微小物体等所有可见元素"

        # Aspect Definitions (Reused)
        aspect_prompts = {
            "风格": "仅提取艺术风格关键词（如：赛博朋克、水墨画、极简主义）。警告：严禁描述画面里的具体事物（如：建筑、街道、人物）！只输出风格流派、笔触、艺术形式！",
            "场景/环境": "仅提取环境地点、天气、氛围关键词（如：室内、雨天、温馨）。警告：严禁描述前景主体或人物！",
            "构图": "镜头角度、构图方式（如：俯视、三分法、特写）。注意：仅描述构图形式，严禁描述画面中具体的物体或人物！",
            "人物外貌": "人物的年龄、种族、发型、五官特征。注意：如果画面没有人物，请输出'无人物'或'None'。",
            "人物动作": "人物的具体动作、姿态、表情。注意：如果画面没有人物，请输出'无人物'或'None'。严禁描述服装或外貌！严禁描述具体的物体（只能用“物体”、“物品”这类词汇来进行描述！",
            "穿搭": "服装款式、材质、颜色、配饰。注意：如果画面没有人物，请输出'无人物'或'None'。严禁描述人物的外貌或动作！",
            "主体物描述": "画面主要物体（非人物）的详细外观。注意：仅描述主体本身，严禁描述背景或环境！",
            "光影描述": "光线来源、质感、阴影分布。",
            "画面配色": "主色调、配色方案。允许使用“主体”、“背景”等抽象词汇描述颜色分布（如“主体为绿色”），但严禁提及具体物体名称（如“树是绿色”）！",
            "摄像机角度": "识别并输出画面的具体拍摄视角（如：平视、俯视、仰视、侧拍、背拍等）。警告：严禁输出“未明确具体视角”！你必须根据画面内容做出判断！严禁描述任何画面内容！",
            "文字/水印": "识别并转录画面中的所有可见文字、水印、LOGO信息，同时要描述文字在画面中的位置以及字体！。若无文字，则不需要出现相关内容。注意：如果用户没有选择此标签，绝对不要在其他标签（如背景、主体）中提及文字或水印内容！"
        }

        # Build message content
        content = []
        
        intro_text = f"""
你是一个专业的AI艺术提示词生成专家。
任务：请分析以下 {len(images)} 张图片，结合每张图片的【指定标签】，直接生成一个融合后的、高质量的Stable Diffusion中文提示词。

**核心生成逻辑（必须严格遵守）：**
1. **识别标签**：首先识别每张图片被打上的具体标签（如构图、背景等）。
2. **生成单图描述**：针对每张图，只生成该图【标签要求描述的内容】。
   - **特别强调**：对于“构图”、“配色”、“摄像机角度”等抽象标签，**严禁**描述画面中具体的物体、人物或场景内容！必须使用“主体”、“物体”、“前景”、“背景”等抽象代词来代替具体名称。
   - 例如：如果标签是“配色”，只能说“主体为红色，背景为深色”，绝对不能说“穿着红裙子的女孩站在黑夜里”。
3. **生成融合提示词**：将上述提取出的、纯净的标签描述内容，融合成一个连贯的画面描述。
4. **最终核查（Self-Correction）**：在输出前，必须再次检查：
   - 检查：我描述的背景是来自选了“场景”标签的那张图吗？
   - 检查：我描述的人物动作是来自选了“动作”标签的那张图吗？
   - 如果发现描述了未选中标签图片的内容，必须立刻修正！
5. **风格处理**：
   - 如果所有图片都没有指定“风格”标签，则由你根据画面内容自动选择最美观的风格。
   - 举例：如果图片1只选了“构图”，图片2只选了“配色”，那么最终画面应该是“图片1的构图 + 图片2的配色”，风格可以自由发挥或跟随图片2（如果有隐含风格）。
6. **融合要求**：
   - 最终输出的提示词是只针对单独一张图的描述，**绝对严禁**出现“图片1”、“图片2”、“图一”、“图二”、“第一张图”等类似的描述！
   - 所有描述必须自然地融为一体，就像是在描述单独的一幅画。
   - 错误示范：“图片1的人物穿着...图片2的背景是...”
   - 正确示范：“人物穿着...背景是...”

**详细要求**：
- **标签优先与互补**：
  - 每张图片都有【指定标签】，请**严格且仅**关注这些标签对应的内容！
  - **白名单机制（White-listing）**：对于每张图，**只能**输出该图【指定标签】对应的描述！如果某张图只选了“摄像机角度”，你的输出里**绝对不能**出现“主体为一位女性”、“身着浅色连衣裙”等内容！只能有一句：“稍低仰拍视角”。
  - 如果某张图没有选择“风格”标签，说明用户**不希望该图片的风格影响最终结果**。
  - 如果所有图片都没有指定“风格”标签，则由你根据画面内容自动选择最美观的风格。
  - **标签绝对权威原则（Universal Tag Authority）**：
    - 对于任何维度（如构图、人物、背景、配色等），**只有选中了该标签的图片**才拥有定义权！
    - 如果图片A选了某标签，而图片B没选，那么该维度的描述**必须完全由图片A决定**。图片B在该维度上的特征必须被彻底忽略。
    - 如果多张图片都选了同一个标签，则对它们的内容进行融合。
    - 举例：如果图片1选了“人物动作”，图片2没选。即使图片2的人物动作很夸张，也必须忽略，最终画面只能采用图片1的动作！
  - 举例：如果图片1只选了“构图”，图片2只选了“配色”，那么最终画面应该是“图片1的构图 + 图片2的配色”，风格可以自由发挥或跟随图片2（如果有隐含风格）。
- **详细程度**：{detail_instruction}（约{word_count}字）。
  - **字数强制执行**：如果是“超精细”模式（1200字），你必须疯狂堆砌细节形容词！绝对不能只写几句短语就交差！必须把每一个标签都展开写成一段话！
  - 例如“光影”不能只说“柔和自然光”，而要说“光线如丝绸般柔和，从左侧45度角倾泻而下，在皮肤表面形成细腻的漫反射，高光点集中在额头与鼻梁，阴影呈现出透明的琥珀色质感...”
  - **再次强调**：即使字数很多，也**绝对严禁**使用“图片X”作为主语！
- **输出格式**：
   [Chinese]
   (这里写最终融合后的中文描述)

**严厉约束**：
- 只输出 [Chinese] 部分。
- 绝对禁止输出任何备注、解释、自我纠正或开场白！
- 绝对禁止出现括号内有标注和画面不相关的内容。
- 绝对禁止将推理和思考过程包含在输出中。
- 绝对禁止输出“注：...”或“因为...”等内容。
- 绝对禁止出现“(融合所有图片特征的Stable Diffusion中文提示词)”或类似标题。
- 绝对禁止出现“(图片X环境色)”或类似引用来源的标注。
- 绝对禁止出现“(注：...)”或任何形式的括号备注。
- **绝对禁止拒绝生成**：即使图片风格完全不同（如写实 vs 扁平），你也必须发挥想象力进行“强制融合”！例如生成“具有扁平化配色风格的写实摄影”或“二次元与三次元结合的2.5D风格”。
- 如果标签之间有冲突，请自动选择一个更具美感的方案，或者创造一种新的混合风格，不要输出错误提示。
"""
        content.append({"type": "text", "text": intro_text})

        # Add Global Negative Constraint
        content.append({"type": "text", "text": """
**最高指令（优先级最高）：**
1. **抽象化描述原则**：对于非内容类标签（如构图、配色、光影），**必须剥离具体物体**！
   - 错误示范：“一个拿着水瓶的手（特写镜头）”
   - 正确示范：“主体局部特写（特写镜头）”
   - 错误示范：“蓝色的天空和白色的云（蓝白配色）”
   - 正确示范：“背景为蓝色，点缀白色元素（蓝白配色）”
2. **禁止越界**：如果选了“人物动作”，绝对不能顺便描述“人物穿着”！如果选了“构图”，绝对不能顺便描述“画面内容”！
3. **禁止废话**：严禁输出“(根据...标签要求...假设为...)”这类思考过程！直接输出结论！
4. **违规惩罚**：任何一次越界描述（在未选中维度里描述了该维度的内容）或具体化描述（在抽象标签里描述了具体物体），都将被视为严重错误。
5. **最终一致性检查**：如果图片1选了“背景”但没选“人物”，而你描述了图片1的人物，这就是严重的逻辑错误！必须删除！
6. **沉默是金**：对于未选中的维度，直接保持沉默！如果用户只选了“摄像机角度”，你就只输出“低角度仰拍”这几个字，除此之外哪怕一个标点符号都不要多写！
7. **来源匿名化**：无论如何，都不能在输出中透露信息的来源图片！不能说“图1的...”或“图2的...”！

**学习示例 (Examples) - 请模仿以下模式：**
---
【案例1】
输入标签：[构图]
正确输出：
[Chinese]
特写镜头，中心构图，浅景深虚化背景。
---
【案例2】
输入标签：[配色]
正确输出：
[Chinese]
主体为暖色调，背景为冷色调，高饱和度，色彩对比强烈。
---
【案例3】
输入标签：[人物动作]
正确输出：
[Chinese]
侧身站立，手持物体，头部微转。
---
【案例4】
输入标签：[风格]
正确输出：
[Chinese]
赛博朋克风格，数字艺术，高对比度，霓虹光感，未来主义美学，颗粒质感。
(错误示范：“赛博朋克风格，街道上有霓虹灯和飞行汽车” -> 错误！不能出现街道和汽车！)

【案例5】
输入标签：[人物动作]
正确输出：
[Chinese]
侧身站立，手持物体，头部微转，微笑表情，
(错误示范：“侧身站立，手持透明瓶子，头部微转，微笑表情，” -> 错误！不能出现具体的物体（如透明瓶子）！)
---
**严禁**出现如“图中有个穿着白衣服的人（配色）”这样的错误输出！必须是抽象的“主体为白色（配色）”。
"""})

        for idx, image_file in enumerate(images):
            # Encode image
            base64_img = encode_image(image_file)
            image_file.seek(0) # Reset pointer
            
            # Get aspects
            selected_aspects = options_map.get(str(idx), [])
            
            # Sort aspects
            normalized_aspects = []
            if selected_aspects and isinstance(selected_aspects[0], dict):
                normalized_aspects = sorted(selected_aspects, key=lambda x: x.get('weight', 1), reverse=True)
            else:
                normalized_aspects = [{'id': a, 'weight': 1} for a in selected_aspects]
                
            aspects_desc = []
            for item in normalized_aspects:
                aspect = item['id']
                # Removed weight logic as requested by user - all tags are treated equally
                if aspect in aspect_prompts:
                    desc = aspect_prompts[aspect]
                    aspects_desc.append(f"{aspect}: {desc}")
                else:
                    # Custom Tag Handling
                    desc = f"仅提取画面中关于“{aspect}”的视觉信息。警告：严禁描述与“{aspect}”无关的任何内容（如人物、背景、光影）！严禁描述该物体与其他物体的关系（如“被拿着”、“放在桌上”）！只输出{aspect}本身的物理特征（如颜色、形状、材质）！"
                    aspects_desc.append(f"{aspect}: {desc}")
            
            aspects_str = "\n".join(aspects_desc) if aspects_desc else "无特定标签约束，请综合分析画面。"

            content.append({"type": "image_url", "image_url": {"url": base64_img}})
            content.append({"type": "text", "text": f"\n[图片 {idx+1} 的参考标签]：\n{aspects_str}\n\n警告：对于这张图片，你只能提取上述列出的标签内容！绝对禁止描述图片中未被标签选中的其他元素！如果标签列表为空，则忽略这张图片的所有内容。"})
        
        print(f"DEBUG: Image encoding and prompt building took {time.time() - start_time:.2f}s")
        api_start_time = time.time()
        
        content.append({"type": "text", "text": "\n请开始直接生成最终融合后的中文提示词："})

        # Call Model
        extra_body = {}
        if use_thinking:
            extra_body["thinking"] = {"type": "enabled"}
        else:
            extra_body["thinking"] = {"type": "disabled"}

        response = client.chat.completions.create(
            model=MODEL_ID,
            messages=[
                {"role": "user", "content": content}
            ],
            extra_body=extra_body
        )
        
        print(f"DEBUG: API Call took {time.time() - api_start_time:.2f}s")
        return response.choices[0].message.content

    except Exception as e:
        print(f"Error in direct fusion: {e}")
        import traceback
        traceback.print_exc()
        raise e

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
    # Parse boolean from string "true"/"false"
    use_thinking = request.form.get('thinking', 'true').lower() == 'true'
    
    if not options_str:
        return jsonify({'error': 'No options provided'}), 400

    try:
        options_map = json.loads(options_str)
    except:
        return jsonify({'error': 'Invalid options format'}), 400

    # Parallel processing replaced by Direct Fusion
    individual_prompts = ["(Direct Fusion Mode - Individual analysis skipped)"] * len(images)
    
    try:
        final_prompt_raw = generate_fused_prompt_directly(images, options_map, precision, use_thinking)
        
        # Post-processing: Aggressively remove unwanted notes
        import re
        final_prompt = final_prompt_raw.replace("[Chinese]", "").strip()
        
        # Remove lines starting with (注 or (Note
        final_prompt = re.sub(r'^\s*[\(（]注.*[\)）]', '', final_prompt, flags=re.MULTILINE)
        
        # Remove any bracketed content at the end if it looks like a note
        final_prompt = re.sub(r'\n\s*[\(（].*?[\)）]\s*$', '', final_prompt, flags=re.DOTALL)
        
        # Remove specific headers like (中文) or (Chinese)
        final_prompt = re.sub(r'^\s*[\(（](中文|Chinese|融合.*)[\)）]\s*', '', final_prompt, flags=re.IGNORECASE)
        
        # New Rule: If the ENTIRE prompt is wrapped in parentheses, remove them
        # Matches: (CONTENT) or （CONTENT）
        # We use dotall to match across newlines
        match_wrapped = re.match(r'^\s*[\(（](.*)[\)）]\s*$', final_prompt, flags=re.DOTALL)
        if match_wrapped:
            final_prompt = match_wrapped.group(1).strip()
            
        final_prompt = final_prompt.strip()
        
    except Exception as e:
        error_str = str(e)
        if "SetLimitExceeded" in error_str:
            final_prompt = "【系统提示】您的火山引擎账户余额不足或已达到“安全体验模式”的限额。\n请前往火山引擎控制台(console.volcengine.com)充值或调整模型限额配置。\n(错误代码: SetLimitExceeded)"
        else:
            final_prompt = f"Error generating prompts: {error_str}"

    return jsonify({
        'final_prompt': final_prompt,
        'individual_prompts': individual_prompts
    })

@app.route('/translate', methods=['POST'])
def translate():
    data = request.json
    text = data.get('text')
    
    if not text:
        return jsonify({'error': 'No text provided'}), 400

    if not client:
        return jsonify({'error': 'Ark client is not initialized. Please check ARK_API_KEY.'}), 500

    try:
        # Create a new translation prompt
        prompt = f"""
你是一个专业的AI翻译助手。请将以下中文提示词翻译成英文提示词（Stable Diffusion/Midjourney格式）。

中文内容：
{text}

要求：
1. **严格直译**：逐字逐句翻译，严禁添加任何额外的修饰词、风格描述或细节！
2. **格式**：使用英文逗号分隔的单词或短语。
3. **一致性**：英文内容必须与中文内容完全对应，不能多也不能少。

请直接输出英文翻译结果，不要有任何其他文字。
"""
        response = client.chat.completions.create(
            model=MODEL_ID,
            messages=[
                {"role": "user", "content": prompt}
            ],
            extra_body={
                "thinking": {"type": "disabled"}
            }
        )
        translated_text = response.choices[0].message.content.strip()
        return jsonify({'translated_text': translated_text})

    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5001))
    app.run(debug=True, host='0.0.0.0', port=port)
