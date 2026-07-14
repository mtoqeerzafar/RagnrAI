import os
import boto3
from botocore.client import Config
from botocore.exceptions import ClientError
from utils.logging import logger
from dotenv import load_dotenv

load_dotenv()

class S3Client:
    def __init__(self):
        self.endpoint_url = os.getenv("S3_ENDPOINT_URL")
        self.access_key = os.getenv("AWS_ACCESS_KEY_ID")
        self.secret_key = os.getenv("AWS_SECRET_ACCESS_KEY")
        self.region = os.getenv("AWS_REGION", "us-east-1")
        self.bucket_name = os.getenv("S3_BUCKET_NAME", "ragnr-documents")

        # Config required for MinIO / S3V4 signatures
        self.s3 = boto3.client(
            's3',
            endpoint_url=self.endpoint_url,
            aws_access_key_id=self.access_key,
            aws_secret_access_key=self.secret_key,
            region_name=self.region,
            config=Config(signature_version='s3v4')
        )
        self._ensure_bucket_exists()

    def _ensure_bucket_exists(self):
        try:
            self.s3.head_bucket(Bucket=self.bucket_name)
        except ClientError as e:
            error_code = e.response['Error']['Code']
            if error_code == '404':
                logger.info(f"Bucket {self.bucket_name} not found. Creating it.")
                self.s3.create_bucket(Bucket=self.bucket_name)
            else:
                logger.error(f"Error checking bucket {self.bucket_name}: {e}")
                raise

    def generate_presigned_upload_url(self, object_name: str, expiration=3600):
        """Generate a presigned URL to upload a file."""
        try:
            response = self.s3.generate_presigned_url(
                'put_object',
                Params={'Bucket': self.bucket_name, 'Key': object_name},
                ExpiresIn=expiration
            )
        except ClientError as e:
            logger.error(e)
            return None
        return response

    def download_file(self, object_name: str, file_path: str):
        """Download a file from S3 to local disk."""
        try:
            self.s3.download_file(self.bucket_name, object_name, file_path)
            logger.info(f"Successfully downloaded {object_name} to {file_path}")
            return True
        except ClientError as e:
            logger.error(f"Error downloading {object_name}: {e}")
            return False

# Global instance for easy import
s3_client = S3Client()
