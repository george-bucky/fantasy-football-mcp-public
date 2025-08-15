#!/bin/bash

# Fantasy Football MCP Server - Google Cloud Run Deployment Script
# This script builds and deploys the Fantasy Football MCP server to Google Cloud Run

set -e  # Exit on any error

# Configuration
PROJECT_ID="${GOOGLE_CLOUD_PROJECT:-ff-mcp}"
PROJECT_NUMBER="399489435570"
REGION="${CLOUD_RUN_REGION:-us-central1}"
SERVICE_NAME="fantasy-football-mcp-server"
IMAGE_NAME="gcr.io/${PROJECT_ID}/${SERVICE_NAME}"
PORT=8080

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

log() {
    echo -e "${BLUE}[$(date +'%Y-%m-%d %H:%M:%S')] $1${NC}"
}

warn() {
    echo -e "${YELLOW}[WARNING] $1${NC}"
}

error() {
    echo -e "${RED}[ERROR] $1${NC}"
    exit 1
}

success() {
    echo -e "${GREEN}[SUCCESS] $1${NC}"
}

# Check prerequisites
check_prerequisites() {
    log "Checking prerequisites..."
    
    # Check if gcloud is installed
    if ! command -v gcloud &> /dev/null; then
        error "gcloud CLI is not installed. Please install it first: https://cloud.google.com/sdk/docs/install"
    fi
    
    # Check if Docker is installed
    if ! command -v docker &> /dev/null; then
        error "Docker is not installed. Please install it first: https://docs.docker.com/get-docker/"
    fi
    
    # Check if logged into gcloud
    if ! gcloud auth list --filter=status:ACTIVE --format="value(account)" | grep -q .; then
        error "Not logged into gcloud. Please run: gcloud auth login"
    fi
    
    success "Prerequisites check passed"
}

# Set up Google Cloud project
setup_project() {
    log "Setting up Google Cloud project..."
    
    # Set project
    gcloud config set project ${PROJECT_ID}
    
    # Enable required APIs
    log "Enabling required APIs..."
    gcloud services enable cloudbuild.googleapis.com
    gcloud services enable run.googleapis.com
    gcloud services enable secretmanager.googleapis.com
    
    success "Project setup completed"
}

# Create secrets in Secret Manager
setup_secrets() {
    log "Setting up secrets in Secret Manager..."
    
    # Check if .env file exists
    if [ ! -f ".env" ]; then
        warn ".env file not found. Please create it with your Yahoo API credentials."
        warn "You can also set secrets manually using: gcloud secrets create SECRET_NAME --data-file=-"
        return
    fi
    
    # Read secrets from .env file and create them
    while IFS='=' read -r key value; do
        # Skip comments and empty lines
        [[ $key =~ ^#.*$ ]] && continue
        [[ -z $key ]] && continue
        
        # Remove quotes and whitespace
        key=$(echo "$key" | tr -d '[:space:]')
        value=$(echo "$value" | sed 's/^"//' | sed 's/"$//' | tr -d '[:space:]')
        
        if [ ! -z "$value" ]; then
            log "Creating secret: $key"
            echo -n "$value" | gcloud secrets create "$key" --data-file=- --replication-policy="automatic" 2>/dev/null || {
                log "Secret $key already exists, updating..."
                echo -n "$value" | gcloud secrets versions add "$key" --data-file=-
            }
        fi
    done < .env
    
    # Create MCP API key if not exists
    if ! gcloud secrets describe MCP_API_KEY &> /dev/null; then
        log "Creating MCP API key..."
        openssl rand -hex 32 | gcloud secrets create MCP_API_KEY --data-file=-
    fi
    
    success "Secrets setup completed"
}

# Build and push Docker image
build_image() {
    log "Building Docker image..."
    
    # Build image
    docker build -t ${IMAGE_NAME}:latest .
    
    # Configure Docker for gcloud
    gcloud auth configure-docker --quiet
    
    # Push image
    log "Pushing image to Google Container Registry..."
    docker push ${IMAGE_NAME}:latest
    
    success "Image built and pushed successfully"
}

# Deploy to Cloud Run
deploy_service() {
    log "Deploying to Cloud Run..."
    
    # Deploy service
    gcloud run deploy ${SERVICE_NAME} \
        --image=${IMAGE_NAME}:latest \
        --region=${REGION} \
        --platform=managed \
        --port=${PORT} \
        --memory=2Gi \
        --cpu=1 \
        --min-instances=0 \
        --max-instances=10 \
        --concurrency=80 \
        --timeout=3600 \
        --no-allow-unauthenticated \
        --set-env-vars="PORT=${PORT}" \
        --set-secrets="YAHOO_CONSUMER_KEY=YAHOO_CONSUMER_KEY:latest" \
        --set-secrets="YAHOO_CONSUMER_SECRET=YAHOO_CONSUMER_SECRET:latest" \
        --set-secrets="YAHOO_ACCESS_TOKEN=YAHOO_ACCESS_TOKEN:latest" \
        --set-secrets="YAHOO_REFRESH_TOKEN=YAHOO_REFRESH_TOKEN:latest" \
        --set-secrets="YAHOO_GUID=YAHOO_GUID:latest" \
        --set-secrets="MCP_API_KEY=MCP_API_KEY:latest" \
        --quiet
    
    success "Service deployed successfully"
}

# Get service URL and set up IAM
setup_access() {
    log "Setting up access..."
    
    # Get service URL
    SERVICE_URL=$(gcloud run services describe ${SERVICE_NAME} --region=${REGION} --format="value(status.url)")
    
    # Get current user email
    USER_EMAIL=$(gcloud auth list --filter=status:ACTIVE --format="value(account)")
    
    # Grant Cloud Run Invoker role to current user
    gcloud run services add-iam-policy-binding ${SERVICE_NAME} \
        --region=${REGION} \
        --member="user:${USER_EMAIL}" \
        --role="roles/run.invoker"
    
    log "Service URL: ${SERVICE_URL}"
    log "Health check: ${SERVICE_URL}/health"
    log "MCP endpoint: ${SERVICE_URL}/mcp"
    
    success "Access setup completed"
}

# Test deployment
test_deployment() {
    log "Testing deployment..."
    
    SERVICE_URL=$(gcloud run services describe ${SERVICE_NAME} --region=${REGION} --format="value(status.url)")
    
    # Test health endpoint
    log "Testing health endpoint..."
    
    # Get access token
    ACCESS_TOKEN=$(gcloud auth print-access-token)
    
    # Test health check
    HEALTH_RESPONSE=$(curl -s -H "Authorization: Bearer ${ACCESS_TOKEN}" "${SERVICE_URL}/health" || echo "FAILED")
    
    if [[ $HEALTH_RESPONSE == *"healthy"* ]]; then
        success "Health check passed"
    else
        warn "Health check failed. Response: $HEALTH_RESPONSE"
    fi
    
    log "Deployment test completed"
}

# Print usage instructions
print_usage() {
    cat << EOF

${GREEN}🎉 Fantasy Football MCP Server deployed successfully!${NC}

${YELLOW}Next steps:${NC}

1. ${BLUE}Test the deployment:${NC}
   gcloud run services proxy ${SERVICE_NAME} --port=8080 --region=${REGION}
   
2. ${BLUE}Get your MCP API key:${NC}
   gcloud secrets versions access latest --secret="MCP_API_KEY"

3. ${BLUE}Configure Claude Desktop:${NC}
   Add this to your Claude Desktop config:
   
   {
     "mcpServers": {
       "fantasy-football": {
         "command": "npx",
         "args": ["-y", "@anthropic-ai/mcp-client"],
         "env": {
           "MCP_SERVER_URL": "$(gcloud run services describe ${SERVICE_NAME} --region=${REGION} --format="value(status.url)")/mcp",
           "MCP_API_KEY": "YOUR_API_KEY_FROM_STEP_2"
         }
       }
     }
   }

4. ${BLUE}Monitor logs:${NC}
   gcloud logging read "resource.type=cloud_run_revision AND resource.labels.service_name=${SERVICE_NAME}" --limit=50

${YELLOW}Important:${NC}
- The service requires authentication
- Use Cloud Run proxy for local testing
- Monitor costs in the Google Cloud Console

EOF
}

# Main execution
main() {
    log "Starting deployment of Fantasy Football MCP Server to Google Cloud Run"
    
    check_prerequisites
    setup_project
    setup_secrets
    build_image
    deploy_service
    setup_access
    test_deployment
    print_usage
    
    success "Deployment completed successfully!"
}

# Execute main function
main "$@"