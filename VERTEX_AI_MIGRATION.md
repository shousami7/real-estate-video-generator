# Vertex AI Setup (Google AI Studio Removed)

This project now runs **exclusively on Vertex AI**. Google AI Studio / API-key flows have been removed from the codebase.

## Prerequisites
- Enable Vertex AI API in your GCP project.
- Authenticate with Application Default Credentials (ADC):
  ```bash
  gcloud auth application-default login
  gcloud config set project <YOUR_PROJECT_ID>
  ```

## Required environment variables
```bash
GOOGLE_CLOUD_PROJECT=<your-gcp-project-id>   # or set GCP_PROJECT_ID
GOOGLE_CLOUD_LOCATION=us-central1            # optional, defaults to us-central1
```

Service accounts also work—set `GOOGLE_APPLICATION_CREDENTIALS` to the key path if you prefer not to use `gcloud auth application-default login`.

## Usage Notes
- Clients are created with `genai.Client(vertexai=True, project=GOOGLE_CLOUD_PROJECT, location=GOOGLE_CLOUD_LOCATION)`.
- All API calls bill to the configured GCP project (uses credits on that project).
- API-key parameters/flags are no longer supported anywhere in the app or tests.
