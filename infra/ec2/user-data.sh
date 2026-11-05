#!/bin/bash
# EC2 첫 부팅에 1번 실행된다 (Amazon Linux 2023). 콘솔의 "고급 세부 정보 > 사용자 데이터"에 붙여 넣는다.
# 비밀값이 없다. 화면 파일과 API 주소는 infra/ec2/deploy_frontend.sh가 나중에 넣는다.
set -euxo pipefail

dnf install -y nginx
mkdir -p /var/www/clicktotrip

cat > /etc/nginx/conf.d/clicktotrip.conf <<'NGINX'
server {
    listen 80 default_server;
    server_name _;
    root /var/www/clicktotrip;
    index index.html;

    include /etc/nginx/clicktotrip-api.inc;

    # 파일 이름에 해시가 붙어 있어 오래 캐시해도 된다
    location /assets/ {
        expires 30d;
        add_header Cache-Control "public, immutable";
    }

    # 화면 경로는 전부 index.html (SPA)
    location / {
        add_header Cache-Control "no-cache";
        try_files $uri /index.html;
    }
}
NGINX

# API Gateway를 만들기 전까지는 503을 돌려준다. deploy_frontend.sh가 이 파일을 바꾼다.
cat > /etc/nginx/clicktotrip-api.inc <<'NGINX'
location /api/ {
    default_type application/json;
    return 503 '{"error":{"code":"API_NOT_CONFIGURED","message":"API Gateway가 아직 연결되지 않았습니다"}}';
}
NGINX

cat > /var/www/clicktotrip/index.html <<'HTML'
<!doctype html><meta charset="utf-8"><title>ClickToTrip</title><p>EC2 준비 완료. 화면 파일을 아직 올리지 않았습니다.</p>
HTML

systemctl enable --now nginx
