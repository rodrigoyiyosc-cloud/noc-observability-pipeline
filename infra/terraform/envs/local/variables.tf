variable "cluster_name" {
  description = "Nombre del clúster kind que crea este entorno."
  type        = string
  default     = "noc-tf"
}

variable "node_image" {
  type        = string
  default     = "kindest/node:v1.37.0@sha256:a1ed56cfb0e7b93589bdf97c8cd566405a265939e3620fc4f5de89adff580ae5"
}