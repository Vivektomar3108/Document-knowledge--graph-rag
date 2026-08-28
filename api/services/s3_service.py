"""
S3 service for file uploads and presigned URL generation.
"""

import boto3
from botocore.exceptions import ClientError
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from api.config import settings
from logger import setup_logger

logger = setup_logger(__name__)


class S3Service:
    """Service for S3 operations."""

    def __init__(self):
        """Initialize S3 client."""
        try:
            logger.info("Initializing S3 service")
            self.s3_client = boto3.client(
                "s3",
                aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
                aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
                region_name=settings.AWS_REGION,
            )
            self.bucket_name = settings.S3_BUCKET_NAME
            logger.info(f"S3 service initialized for bucket: {self.bucket_name}")
        except Exception as e:
            logger.error(f"Failed to initialize S3 client: {e}", exc_info=True)
            raise

    async def upload_file(
        self, local_file_path: str, s3_key: str
    ) -> Optional[str]:
        """
        Upload a file to S3.

        Args:
            local_file_path: Path to the local file
            s3_key: S3 object key (path in bucket)

        Returns:
            S3 key if successful, None otherwise
        """
        logger.info(f"Uploading file {local_file_path} to S3 key: {s3_key}")
        try:
            # Check if file exists before attempting upload
            from pathlib import Path
            if not Path(local_file_path).exists():
                logger.error(f"Local file not found: {local_file_path}")
                return None

            # Get file size for logging
            file_size = Path(local_file_path).stat().st_size
            logger.debug(f"File size: {file_size} bytes")

            # Perform upload
            self.s3_client.upload_file(local_file_path, self.bucket_name, s3_key)
            logger.info(f"Successfully uploaded {local_file_path} ({file_size} bytes) to s3://{self.bucket_name}/{s3_key}")
            return s3_key
        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', 'Unknown')
            logger.error(f"S3 ClientError uploading {local_file_path}: {error_code} - {e}", exc_info=True)
            return None
        except FileNotFoundError:
            logger.error(f"Local file not found: {local_file_path}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error uploading {local_file_path} to S3: {e}", exc_info=True)
            return None

    async def generate_presigned_url(
        self, s3_key: str, expiration: Optional[int] = None
    ) -> Optional[str]:
        """
        Generate a presigned URL for downloading a file from S3.

        Args:
            s3_key: S3 object key
            expiration: URL expiration time in seconds (default: from settings)

        Returns:
            Presigned URL if successful, None otherwise
        """
        logger.info(f"Generating presigned URL for S3 key: {s3_key}")

        if expiration is None:
            expiration = settings.S3_PRESIGNED_URL_EXPIRY

        try:
            # Validate S3 key is not None or empty
            if not s3_key:
                logger.error("S3 key is None or empty")
                return None

            url = self.s3_client.generate_presigned_url(
                "get_object",
                Params={"Bucket": self.bucket_name, "Key": s3_key},
                ExpiresIn=expiration,
            )
            logger.info(f"Generated presigned URL for {s3_key}, expires in {expiration}s")
            return url
        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', 'Unknown')
            logger.error(f"S3 ClientError generating presigned URL for {s3_key}: {error_code} - {e}", exc_info=True)
            return None
        except Exception as e:
            logger.error(f"Unexpected error generating presigned URL for {s3_key}: {e}", exc_info=True)
            return None

    async def delete_file(self, s3_key: str) -> bool:
        """
        Delete a file from S3.

        Args:
            s3_key: S3 object key

        Returns:
            True if successful, False otherwise
        """
        logger.info(f"Deleting S3 file: {s3_key}")

        try:
            # Validate S3 key is not None or empty
            if not s3_key:
                logger.error("S3 key is None or empty")
                return False

            self.s3_client.delete_object(Bucket=self.bucket_name, Key=s3_key)
            logger.info(f"Successfully deleted {s3_key} from S3")
            return True
        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', 'Unknown')
            logger.error(f"S3 ClientError deleting {s3_key}: {error_code} - {e}", exc_info=True)
            return False
        except Exception as e:
            logger.error(f"Unexpected error deleting {s3_key} from S3: {e}", exc_info=True)
            return False

    async def upload_pipeline_outputs(
        self, process_id: str, unique_entities_path: str, references_path: str
    ) -> tuple[Optional[str], Optional[str]]:
        """
        Upload the two final pipeline output files to S3.

        Args:
            process_id: Pipeline run process ID
            unique_entities_path: Local path to unique_entities.csv
            references_path: Local path to references.csv

        Returns:
            Tuple of (unique_entities_s3_key, references_s3_key)
        """
        logger.info(f"Uploading pipeline outputs for process {process_id}")

        try:
            # Define S3 keys
            unique_entities_key = f"outputs/{process_id}/unique_entities.csv"
            references_key = f"outputs/{process_id}/references.csv"

            logger.debug(f"Unique entities S3 key: {unique_entities_key}")
            logger.debug(f"References S3 key: {references_key}")

            # Upload files
            unique_entities_s3_key = await self.upload_file(
                unique_entities_path, unique_entities_key
            )
            references_s3_key = await self.upload_file(references_path, references_key)

            if unique_entities_s3_key and references_s3_key:
                logger.info(f"Successfully uploaded both pipeline outputs for process {process_id}")
            else:
                logger.warning(f"Failed to upload one or more pipeline outputs for process {process_id}")

            return unique_entities_s3_key, references_s3_key
        except Exception as e:
            logger.error(f"Unexpected error uploading pipeline outputs for process {process_id}: {e}", exc_info=True)
            return None, None

    def get_expiry_time(self, expiration_seconds: Optional[int] = None) -> datetime:
        """
        Calculate expiry time for presigned URLs.

        Args:
            expiration_seconds: Expiration time in seconds

        Returns:
            Expiry datetime
        """
        if expiration_seconds is None:
            expiration_seconds = settings.S3_PRESIGNED_URL_EXPIRY
        return datetime.utcnow() + timedelta(seconds=expiration_seconds)
