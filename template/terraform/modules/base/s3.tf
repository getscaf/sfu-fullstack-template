resource "aws_s3_bucket" "backups" {
  bucket = "${var.app_name}-${var.environment}-backups"
  tags   = local.common_tags
}

resource "aws_s3_bucket_server_side_encryption_configuration" "backups" {
  bucket = aws_s3_bucket.backups.bucket
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket" "static_storage" {
  bucket = "${var.app_name}-${var.environment}-static-storage"
  tags   = local.common_tags
}

resource "aws_s3_bucket_public_access_block" "static_storage" {
  bucket                  = aws_s3_bucket.static_storage.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "static_storage" {
  bucket = aws_s3_bucket.static_storage.bucket

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_cors_configuration" "static_storage" {
  bucket = aws_s3_bucket.static_storage.id

  cors_rule {
    allowed_headers = ["Authorization", "Content-Length"]
    allowed_methods = [
      "GET",
      "PUT",
      "POST",
      "DELETE",
      "HEAD"
    ]
    allowed_origins = ["*"]
  }
}

resource "aws_s3_bucket_versioning" "static_storage" {
  bucket = aws_s3_bucket.static_storage.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_ownership_controls" "static_storage" {
  bucket = aws_s3_bucket.static_storage.id
  rule {
    object_ownership = "ObjectWriter"
  }
}

resource "aws_s3_bucket_acl" "static_storage" {
  depends_on = [aws_s3_bucket_ownership_controls.static_storage]

  bucket = aws_s3_bucket.static_storage.id
  acl    = "private"
}

resource "aws_s3_bucket_policy" "static_storage" {
  bucket = aws_s3_bucket.static_storage.id
  policy = <<EOF
{
    "Version": "2012-10-17",
    "Statement": {
        "Sid": "AllowCloudFrontServicePrincipalReadOnly",
        "Effect": "Allow",
        "Principal": {
            "Service": "cloudfront.amazonaws.com"
        },
        "Action": "s3:GetObject",
        "Resource": {% if copier__use_wagtail %}[
            "${aws_s3_bucket.static_storage.arn}/static/*",
            "${aws_s3_bucket.static_storage.arn}/media/original_images/*",
            "${aws_s3_bucket.static_storage.arn}/media/images/*",
            "${aws_s3_bucket.static_storage.arn}/media/avatar_images/*"
        ]{% else %}"${aws_s3_bucket.static_storage.arn}/*"{% endif %},
        "Condition": {
            "StringEquals": {
                "AWS:SourceArn": "${aws_cloudfront_distribution.cloudfront.arn}"
            }
        }
    }
}
EOF
}
