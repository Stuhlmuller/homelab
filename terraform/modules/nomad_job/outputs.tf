output "job_name" {
  description = "Nomad job name."
  value       = nomad_job.this.name
}

output "job_status" {
  description = "Nomad job status."
  value       = nomad_job.this.status
}
