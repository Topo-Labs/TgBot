#!/bin/bash

# Telegram Bot 部署脚本

set -e

echo "🚀 Starting Telegram Bot deployment..."

# 检查Docker是否安装
if ! command -v docker &> /dev/null; then
    echo "❌ Docker is not installed. Please install Docker first."
    exit 1
fi

if ! command -v docker-compose &> /dev/null; then
    echo "❌ Docker Compose is not installed. Please install Docker Compose first."
    exit 1
fi

# 检查.env文件是否存在
if [ ! -f .env ]; then
    echo "❌ .env file not found. Please copy .env.example to .env and configure it."
    exit 1
fi

# 创建必要的目录
mkdir -p logs

# 停止现有容器（如果存在）
echo "🛑 Stopping existing containers..."
docker-compose down || true

# 构建并启动容器
echo "🔨 Building and starting containers..."
docker-compose up -d --build

# 等待服务启动
echo "⏳ Waiting for services to start..."
sleep 10

# 检查服务状态
echo "📊 Checking service status..."
docker-compose ps

# 显示日志
echo "📋 Showing bot logs..."
docker-compose logs -f bot