output "volume_id" {
  description = "Registered CSI volume ID."
  value       = nomad_csi_volume_registration.this.volume_id
}
