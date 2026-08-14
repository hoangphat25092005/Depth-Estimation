import boto3
from configs.setting import STORAGE_DOMAIN, STORAGE_ACCESS_KEY, STORAGE_SECRET_KEY

S3_bucket_name_original = "011"
S3_bucket_name_depth = "012"

s3_client = boto3.client(
    's3', 
    endpoint_url=STORAGE_DOMAIN, 
    aws_access_key_id=STORAGE_ACCESS_KEY,  # Access key của MinIO
    aws_secret_access_key=STORAGE_SECRET_KEY, # Secret key của MinIO
    region_name="us-east-1"
)