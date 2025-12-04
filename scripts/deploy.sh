#!/bin/bash

# AETHER Production Deployment Script
set -e

echo "🚀 Starting AETHER AI Accounting Platform Production Deployment..."
echo "================================================================"

# Load environment variables
if [ -f .env.prod ]; then
    export $(cat .env.prod | grep -v '^#' | xargs)
    echo "Loaded production environment variables"
else
    echo "Warning: .env.prod not found. Using default values."
fi

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Logging function
log() {
    echo -e "${BLUE}[$(date +'%Y-%m-%d %H:%M:%S')]${NC} $1"
}

success() {
    echo -e "${GREEN}✓${NC} $1"
}

error() {
    echo -e "${RED}✗${NC} $1"
}

warning() {
    echo -e "${YELLOW}!${NC} $1"
}

# Check prerequisites
check_prerequisites() {
    log "Checking prerequisites..."
    
    # Check Docker
    if ! command -v docker &> /dev/null; then
        error "Docker is not installed. Please install Docker first."
        exit 1
    fi
    success "Docker installed"
    
    # Check Docker Compose
    if ! command -v docker-compose &> /dev/null; then
        error "Docker Compose is not installed. Please install Docker Compose first."
        exit 1
    fi
    success "Docker Compose installed"
    
    # Check CPU architecture
    ARCH=$(uname -m)
    if [[ "$ARCH" != "x86_64" ]] && [[ "$ARCH" != "aarch64" ]]; then
        warning "Unsupported architecture: $ARCH. Some features may not work correctly."
    fi
    
    # Check available memory
    MEM_GB=$(free -g | awk '/^Mem:/{print $2}')
    if [ "$MEM_GB" -lt 4 ]; then
        warning "Low memory detected: ${MEM_GB}GB. Minimum 4GB recommended for production."
    fi
    
    # Check disk space
    DISK_GB=$(df -BG / | awk 'NR==2{print $4}' | sed 's/G//')
    if [ "$DISK_GB" -lt 20 ]; then
        warning "Low disk space: ${DISK_GB}GB. Minimum 20GB recommended."
    fi
    
    success "Prerequisites check passed"
}

# Setup directories
setup_directories() {
    log "Setting up directories..."
    
    mkdir -p ./data
    mkdir -p ./logs/{app,nginx}
    mkdir -p ./uploads
    mkdir -p ./ml/models
    mkdir -p ./nginx/ssl
    mkdir -p ./prometheus
    mkdir -p ./grafana/{dashboards,provisioning}
    mkdir -p ./vector
    
    # Set permissions
    chmod 755 ./data ./logs ./uploads
    chmod 644 .env.prod 2>/dev/null || true
    
    success "Directories created"
}

# Generate SSL certificates
generate_ssl() {
    log "Setting up SSL certificates..."
    
    if [ ! -f ./nginx/ssl/cert.pem ] || [ ! -f ./nginx/ssl/key.pem ]; then
        warning "SSL certificates not found in ./nginx/ssl/"
        warning "Please place your SSL certificates as:"
        warning "  - ./nginx/ssl/cert.pem (certificate)"
        warning "  - ./nginx/ssl/key.pem (private key)"
        warning "Or use Let's Encrypt certificates in /etc/letsencrypt/"
        
        read -p "Generate self-signed certificates for testing? (y/n): " -n 1 -r
        echo
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            log "Generating self-signed certificates..."
            openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
                -keyout ./nginx/ssl/key.pem \
                -out ./nginx/ssl/cert.pem \
                -subj "/C=US/ST=State/L=City/O=Organization/CN=aether.ai"
            success "Self-signed certificates generated"
        else
            warning "SSL certificates are required for HTTPS. Continuing without..."
        fi
    else
        success "SSL certificates found"
    fi
}

# Initialize database
init_database() {
    log "Initializing database..."
    
    # Wait for PostgreSQL to be ready
    log "Waiting for PostgreSQL to be ready..."
    for i in {1..30}; do
        if docker-compose -f docker-compose.prod.yml exec -T postgres pg_isready -U ${DB_USER:-aether_user}; then
            success "PostgreSQL is ready"
            break
        fi
        if [ $i -eq 30 ]; then
            error "PostgreSQL failed to start"
            exit 1
        fi
        sleep 2
    done
    
    # Run database migrations
    log "Running database migrations..."
    docker-compose -f docker-compose.prod.yml exec -T backend \
        python -m alembic upgrade head
    
    # Seed initial data
    log "Seeding initial data..."
    docker-compose -f docker-compose.prod.yml exec -T backend \
        python scripts/setup_db.py
    
    success "Database initialized"
}

# Build and start services
start_services() {
    log "Building and starting services..."
    
    # Pull latest images
    docker-compose -f docker-compose.prod.yml pull
    
    # Build images
    docker-compose -f docker-compose.prod.yml build --no-cache
    
    # Start services
    docker-compose -f docker-compose.prod.yml up -d
    
    # Wait for services to be healthy
    log "Waiting for services to be healthy..."
    sleep 10
    
    # Check backend health
    for i in {1..30}; do
        if curl -f http://localhost:8000/health > /dev/null 2>&1; then
            success "Backend is healthy"
            break
        fi
        if [ $i -eq 30 ]; then
            error "Backend failed to start"
            docker-compose -f docker-compose.prod.yml logs backend
            exit 1
        fi
        sleep 2
    done
    
    # Check frontend health
    for i in {1..30}; do
        if curl -f http://localhost:3000 > /dev/null 2>&1; then
            success "Frontend is healthy"
            break
        fi
        sleep 2
    done
    
    success "All services started successfully"
}

# Train ML models
train_models() {
    log "Training ML models..."
    
    # Check if models already exist
    if [ -f "./ml/models/category_classifier.pkl" ] && [ -f "./ml/models/anomaly_detector.pkl" ]; then
        warning "ML models already exist. Skipping training."
        return
    fi
    
    # Train category classifier
    log "Training category classifier..."
    docker-compose -f docker-compose.prod.yml exec -T backend \
        python ml/training/train_categories.py
    
    # Train anomaly detector
    log "Training anomaly detector..."
    docker-compose -f docker-compose.prod.yml exec -T backend \
        python ml/training/train_anomalies.py
    
    success "ML models trained"
}

# Setup monitoring
setup_monitoring() {
    log "Setting up monitoring..."
    
    # Import Grafana dashboards
    if [ -f "./grafana/dashboards/dashboard.json" ]; then
        log "Importing Grafana dashboards..."
        # This would require Grafana API calls
        # For now, we'll just copy the files
        docker-compose -f docker-compose.prod.yml cp \
            ./grafana/dashboards/. grafana:/var/lib/grafana/dashboards/
    fi
    
    # Setup alerting rules
    if [ -f "./prometheus/rules.yml" ]; then
        docker-compose -f docker-compose.prod.yml cp \
            ./prometheus/rules.yml prometheus:/etc/prometheus/rules.yml
        docker-compose -f docker-compose.prod.yml exec -T prometheus \
            kill -HUP 1
    fi
    
    success "Monitoring setup complete"
}

# Verify deployment
verify_deployment() {
    log "Verifying deployment..."
    
    # Check API endpoints
    endpoints=(
        "/health"
        "/api/v1/auth/me"
        "/api/v1/transactions/stats/summary"
    )
    
    for endpoint in "${endpoints[@]}"; do
        if curl -f "http://localhost:8000${endpoint}" > /dev/null 2>&1; then
            success "Endpoint ${endpoint} is accessible"
        else
            warning "Endpoint ${endpoint} is not accessible"
        fi
    done
    
    # Check services status
    services=("backend" "frontend" "postgres" "redis")
    for service in "${services[@]}"; do
        if docker-compose -f docker-compose.prod.yml ps | grep -q "${service}.*Up"; then
            success "Service ${service} is running"
        else
            warning "Service ${service} is not running"
        fi
    done
    
    # Check disk usage
    log "Checking disk usage..."
    df -h ./data ./logs ./uploads
    
    success "Deployment verification complete"
}

# Print deployment info
print_deployment_info() {
    echo ""
    echo "================================================================"
    echo "🎉 AETHER AI Accounting Platform Deployment Complete!"
    echo "================================================================"
    echo ""
    echo "📊 Services:"
    echo "   • Backend API:      http://localhost:8000"
    echo "   • Frontend App:     http://localhost:3000"
    echo "   • API Documentation: http://localhost:8000/api/docs"
    echo "   • Grafana:          http://localhost:3001 (admin/${GRAFANA_PASSWORD:-admin})"
    echo "   • pgAdmin:          http://localhost:5050"
    echo "   • Redis Commander:  http://localhost:8081"
    echo ""
    echo "🔧 Management Commands:"
    echo "   • View logs:        docker-compose -f docker-compose.prod.yml logs -f"
    echo "   • Stop services:    docker-compose -f docker-compose.prod.yml down"
    echo "   • Restart services: docker-compose -f docker-compose.prod.yml restart"
    echo "   • Update services:  docker-compose -f docker-compose.prod.yml pull && docker-compose -f docker-compose.prod.yml up -d"
    echo ""
    echo "📈 Next Steps:"
    echo "   1. Access the frontend at http://localhost:3000"
    echo "   2. Login with admin@aether.ai / admin123"
    echo "   3. Connect your bank accounts via Plaid"
    echo "   4. Upload receipts for AI processing"
    echo "   5. Set up automated reports"
    echo ""
    echo "⚠️  Important Security Notes:"
    echo "   • Change default admin password immediately"
    echo "   • Set up proper SSL certificates for production"
    echo "   • Configure firewall rules"
    echo "   • Set up automated backups"
    echo "   • Monitor resource usage"
    echo ""
    echo "For support, check the documentation or open an issue."
    echo "================================================================"
}

# Main deployment flow
main() {
    echo "Starting AETHER deployment at $(date)"
    echo "=========================================="
    
    # Check prerequisites
    check_prerequisites
    
    # Setup directories
    setup_directories
    
    # Generate SSL certificates
    generate_ssl
    
    # Build and start services
    start_services
    
    # Initialize database
    init_database
    
    # Train ML models
    train_models
    
    # Setup monitoring
    setup_monitoring
    
    # Verify deployment
    verify_deployment
    
    # Print deployment info
    print_deployment_info
    
    success "Deployment completed successfully at $(date)"
}

# Handle errors
trap 'error "Deployment failed at $(date)"; exit 1' ERR

# Run main function
main "$@"
