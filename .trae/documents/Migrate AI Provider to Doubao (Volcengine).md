I will migrate the backend from ZhipuAI to Volcengine (Doubao) as requested.

### 1. Install Dependencies
- Install the official Volcengine SDK: `pip install 'volcengine-python-sdk[ark]'`

### 2. Update Configuration (.env)
- Remove `ZHIPU_API_KEY`.
- Add `ARK_API_KEY=edf9bac4-5233-47d1-8f31-eaa907e31dbb`.
- Update `MODEL_ID` to `doubao-seed-1-6-flash-250828`.

### 3. Refactor Backend (app.py)
- **Import Changes**: Replace `zhipuai` with `volcenginesdkarkruntime`.
- **Client Initialization**: Update the client to use `Ark` with the Volcengine base URL (`https://ark.cn-beijing.volces.com/api/v3`).
- **Logic Update**: Ensure both `analyze_single_image` (Vision task) and `merge_prompts` (Text task) use the new Doubao client. *Note: I will assume the provided model ID supports image inputs.*

### 4. Restart Server
- Restart the Flask application to apply changes.