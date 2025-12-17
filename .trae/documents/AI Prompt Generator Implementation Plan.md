# AI Prompt Generator (Doubao Integration)

## Implementation Details
1.  **Backend (Flask)**:
    -   Handles image uploads and API communication.
    -   Integrates with Volcengine Ark SDK (`volcenginesdkarkruntime`) to call Doubao models.
    -   Implements logic to analyze individual images based on selected aspects.
    -   Implements logic to combine multiple prompts into a cohesive final prompt.
    -   Error handling ensures network or API issues are reported clearly.

2.  **Frontend (HTML/Tailwind)**:
    -   Clean, responsive UI.
    -   Supports multiple image uploads.
    -   Dynamic aspect selection for each image (Style, Background, etc.).
    -   Real-time status updates and error messages.

3.  **Project Structure**:
    -   `app.py`: Main application logic.
    -   `templates/index.html`: User interface.
    -   `requirements.txt`: Dependencies.
    -   `.env.example`: Configuration template.
    -   `venv/`: Virtual environment (contains all installed packages).

## Setup Instructions

### 1. Configure Credentials
You need to set up your API Key and Model Endpoint ID.
1.  Rename `.env.example` to `.env`.
2.  Edit `.env` and fill in your details:
    ```bash
    ARK_API_KEY=your_api_key_here
    ARK_MODEL_ID=your_vision_model_endpoint_id_here
    ```
    *Note: Ensure your `ARK_MODEL_ID` corresponds to a Vision-capable model endpoint (e.g., `doubao-vision-pro`). Standard text models cannot process images.*

### 2. Run the Application
Execute the following command in the project directory:
```bash
./venv/bin/python app.py
```

### 3. Access the Webpage
Open your browser and navigate to:
`http://127.0.0.1:5000`

## Features
-   **Multi-Image Support**: Upload as many images as needed.
-   **Granular Control**: Select specific aspects (Style, Outfit, etc.) for each image.
-   **Conflict Resolution**: The AI automatically blends conflicting descriptions into a harmonious final prompt.
-   **Clean Workspace**: All temporary files are automatically cleaned up after processing.
