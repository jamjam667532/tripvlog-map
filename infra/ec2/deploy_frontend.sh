#!/usr/bin/env bash
# 프론트를 빌드해 EC2에 올린다. 저장소 루트에서 실행한다.
#   bash infra/ec2/deploy_frontend.sh <EC2 공인 IP> <키 파일.pem> [API Gateway 호스트]
# 호스트 예: abc123.execute-api.ap-northeast-2.amazonaws.com (https://, 경로 없이)
# 호스트를 주면 nginx의 /api/ 전달도 함께 바꾼다. 없으면 화면 파일만 올린다.
set -euo pipefail

IP=${1:?EC2 공인 IP가 필요합니다}
PEM=${2:?키 파일(.pem) 경로가 필요합니다}
API_HOST=${3:-}
SSH=(ssh -i "$PEM" -o StrictHostKeyChecking=accept-new "ec2-user@$IP")

# VITE_API_BASE가 없으면 프론트는 가짜 API로 동작한다. 지도 키는 .env.local에서 읽는다.
[ -f frontend/.env.local ] || { echo "frontend/.env.local이 없습니다 (VITE_GOOGLE_MAPS_API_KEY)" >&2; exit 1; }
(cd frontend && { [ -d node_modules ] || npm ci; } && VITE_API_BASE=/api npm run build)

tar -C frontend/dist -cf - . | "${SSH[@]}" \
  "sudo find /var/www/clicktotrip -mindepth 1 -delete && sudo tar -xf - -C /var/www/clicktotrip"

if [ -n "$API_HOST" ]; then
  # 변수로 넘기고 resolver를 두어 API Gateway IP가 바뀌어도 따라가게 한다. 169.254.169.253은 VPC DNS.
  "${SSH[@]}" "sudo tee /etc/nginx/clicktotrip-api.inc >/dev/null" <<NGINX
location /api/ {
    resolver 169.254.169.253 valid=60s;
    set \$api_host $API_HOST;
    rewrite ^/api/(.*)\$ /\$1 break;
    proxy_pass https://\$api_host;
    proxy_http_version 1.1;
    proxy_set_header Connection "";
    proxy_ssl_server_name on;
    proxy_ssl_name \$api_host;
    proxy_set_header Host \$api_host;
    proxy_read_timeout 30s;
    add_header Cache-Control "no-store" always;
}
NGINX
  "${SSH[@]}" "sudo nginx -t && sudo systemctl reload nginx"
fi

echo "완료: http://$IP"
