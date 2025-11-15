# Vertex AI Migration Guide

## Overview

This project now supports **both Google AI Studio and Vertex AI** for video generation using Veo API.

### Why Migrate to Vertex AI?

| Feature | Google AI Studio | Vertex AI |
|---------|-----------------|-----------|
| **Cost** | Pay-per-use (independent billing) | **GCP Credits Available** (¥45,602+) |
| **Billing** | Separate API billing | Integrated with GCP billing |
| **Rate Limits** | Stricter limits | Enterprise-level quotas |
| **Authentication** | API Key | Service Account (more secure) |
| **Scalability** | Limited | Production-ready |
| **For Startups** | Development/Testing | **Production Recommended** |

---

## Migration Steps

### 1. Enable Vertex AI API in GCP

```bash
# Set your GCP project ID
export PROJECT_ID="your-gcp-project-id"

# Enable required APIs
gcloud services enable aiplatform.googleapis.com
gcloud services enable generativelanguage.googleapis.com
```

### 2. Setup Authentication

#### Option A: Application Default Credentials (Recommended for local development)

```bash
# Login to GCP
gcloud auth application-default login

# Set project
gcloud config set project $PROJECT_ID
```

#### Option B: Service Account (Recommended for production)

```bash
# Create service account
gcloud iam service-accounts create veo-video-generator \
    --display-name="Veo Video Generator Service Account"

# Grant necessary permissions
gcloud projects add-iam-policy-binding $PROJECT_ID \
    --member="serviceAccount:veo-video-generator@${PROJECT_ID}.iam.gserviceaccount.com" \
    --role="roles/aiplatform.user"

# Create and download key
gcloud iam service-accounts keys create ~/veo-sa-key.json \
    --iam-account=veo-video-generator@${PROJECT_ID}.iam.gserviceaccount.com

# Set environment variable
export GOOGLE_APPLICATION_CREDENTIALS=~/veo-sa-key.json
```

### 3. Install Dependencies

```bash
# Install updated dependencies
pip install -r requirements.txt
```

### 4. Configure Environment Variables

Create or update `.env` file:

```bash
# For Vertex AI (RECOMMENDED - uses GCP credits)
GOOGLE_CLOUD_PROJECT=your-gcp-project-id
GOOGLE_CLOUD_LOCATION=us-central1  # Optional, defaults to us-central1

# For Google AI Studio (fallback)
# GOOGLE_API_KEY=your-api-key-here

# Other settings
REDIS_URL=redis://localhost:6379/0
```

**Important:** If `GOOGLE_CLOUD_PROJECT` is set, the system will automatically use Vertex AI mode. Otherwise, it falls back to Google AI Studio mode.

---

## Usage

### CLI Usage

#### Vertex AI Mode (Recommended)

```bash
# Basic usage
python generate_property_video.py \
  --use-vertex-ai \
  --project-id your-gcp-project-id \
  --images exterior.jpg interior.jpg lobby.jpg

# With custom location
python generate_property_video.py \
  --use-vertex-ai \
  --project-id your-gcp-project-id \
  --location asia-northeast1 \
  --images photo1.jpg photo2.jpg photo3.jpg

# With environment variables (easier)
export GOOGLE_CLOUD_PROJECT=your-gcp-project-id
python generate_property_video.py \
  --use-vertex-ai \
  --images img1.jpg img2.jpg img3.jpg
```

#### Google AI Studio Mode (Legacy)

```bash
export GOOGLE_API_KEY=your-api-key
python generate_property_video.py \
  --api-key $GOOGLE_API_KEY \
  --images exterior.jpg interior.jpg lobby.jpg
```

### Web UI Usage

The Web UI **automatically detects** which mode to use based on environment variables:

1. **Vertex AI Mode** (if `GOOGLE_CLOUD_PROJECT` is set):
   ```bash
   export GOOGLE_CLOUD_PROJECT=your-gcp-project-id
   export GOOGLE_CLOUD_LOCATION=us-central1  # Optional
   python app.py
   ```

2. **Google AI Studio Mode** (if only `GOOGLE_API_KEY` is set):
   ```bash
   export GOOGLE_API_KEY=your-api-key
   python app.py
   ```

### Celery Worker Usage

```bash
# Start Celery worker (uses environment variables)
celery -A celery_app worker --loglevel=info
```

---

## Cost Estimation

### Vertex AI Pricing (as of 2025)

- **Veo 3.1 Fast**: ~$0.15 per 8-second video generation
- **Your GCP Credits**: ¥45,602 ≈ $305 USD

**Estimated Videos:**
- With ¥45,602 credits: **~2,000 videos** (3 clips each = 6,000 clips total)
- Per property video (3 clips): **~$0.45**

### Cost Savings

| Scenario | Google AI Studio | Vertex AI (with credits) |
|----------|-----------------|--------------------------|
| 100 property videos | $45 | **$0** (uses credits) |
| 500 property videos | $225 | **$0** (uses credits) |
| 2000 property videos | $900 | **$135** (after credits) |

---

## Comparison: Google AI Studio vs Vertex AI

### Code Differences

Both modes use the **same API interface** with different initialization:

```python
# Google AI Studio
from veo_generator import VeoVideoGenerator

generator = VeoVideoGenerator(
    api_key="your-api-key"
)

# Vertex AI
generator = VeoVideoGenerator(
    project_id="your-gcp-project-id",
    location="us-central1",
    use_vertex_ai=True
)
```

### Model Differences

| Mode | Model Used |
|------|-----------|
| Google AI Studio | `veo-3.0-fast-generate-001` |
| Vertex AI | `veo-3.1-generate-preview` |

---

## Troubleshooting

### Error: "GOOGLE_CLOUD_PROJECT not found"

**Solution:**
```bash
export GOOGLE_CLOUD_PROJECT=your-gcp-project-id
```

### Error: "Permission denied" or "403 Forbidden"

**Solution:** Ensure your service account has the correct permissions:
```bash
gcloud projects add-iam-policy-binding $PROJECT_ID \
    --member="serviceAccount:veo-video-generator@${PROJECT_ID}.iam.gserviceaccount.com" \
    --role="roles/aiplatform.user"
```

### Error: "API not enabled"

**Solution:**
```bash
gcloud services enable aiplatform.googleapis.com
gcloud services enable generativelanguage.googleapis.com
```

### Error: "Default credentials not found"

**Solution:**
```bash
gcloud auth application-default login
```

### Check Current Mode

The system logs will clearly indicate which mode is being used:

```
✓ Vertex AI Mode - Using GCP credits
✓ Model: veo-3.1-generate-preview
✓ Project: your-gcp-project-id
✓ Location: us-central1
```

or

```
✓ Google AI Studio Mode
✓ Model: veo-3.0-fast-generate-001
```

---

## Migration Checklist

- [ ] Enable Vertex AI API in GCP
- [ ] Setup authentication (Application Default Credentials or Service Account)
- [ ] Install updated dependencies: `pip install -r requirements.txt`
- [ ] Set environment variables (`GOOGLE_CLOUD_PROJECT`, `GOOGLE_CLOUD_LOCATION`)
- [ ] Test with a single video generation
- [ ] Verify GCP billing/credits are being used
- [ ] Update production environment variables
- [ ] Train team on new CLI flags

---

## Rollback Plan

If you need to rollback to Google AI Studio:

1. Remove or unset `GOOGLE_CLOUD_PROJECT`:
   ```bash
   unset GOOGLE_CLOUD_PROJECT
   ```

2. Set Google AI Studio API key:
   ```bash
   export GOOGLE_API_KEY=your-api-key
   ```

3. Restart services

---

## Support

For issues or questions:
- Check logs for mode detection: `✓ Vertex AI Mode` or `✓ Google AI Studio Mode`
- Review GCP quotas: https://console.cloud.google.com/iam-admin/quotas
- Check Vertex AI status: https://status.cloud.google.com/

---

## Next Steps

1. **Test migration**: Generate 1 test video with `--use-vertex-ai`
2. **Monitor costs**: Check GCP billing console
3. **Scale up**: Use Vertex AI for all production workloads
4. **Optimize**: Adjust polling intervals if needed (already optimized for cost)

**Your ¥45,602 GCP credits are now ready to use!** 🚀
