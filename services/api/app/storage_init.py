from botocore.exceptions import ClientError

from app.core.config import get_settings
from app.services.dependencies import storage_client


def main() -> None:
    client = storage_client()
    bucket = get_settings().s3_bucket
    try:
        client.head_bucket(Bucket=bucket)
    except ClientError as exc:
        if exc.response["ResponseMetadata"]["HTTPStatusCode"] != 404:
            raise
        client.create_bucket(Bucket=bucket)
    print("Object storage bucket is ready")


if __name__ == "__main__":
    main()
