output "bucket_name" {
  value = b2_bucket.raw.bucket_name
}

output "bucket_id" {
  value = b2_bucket.raw.bucket_id
}

output "upload_key_id" {
  value = b2_application_key.capture_upload.application_key_id
}

output "read_key_id" {
  value = b2_application_key.tripwire_read.application_key_id
}
