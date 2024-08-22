docker buildx create --name mybuilder --use
docker buildx build --platform linux/amd64 -t XXX.dkr.ecr.us-east-1.amazonaws.com/XXX:XXX . --push