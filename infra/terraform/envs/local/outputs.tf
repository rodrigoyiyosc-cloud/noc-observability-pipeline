output "cluster_name" {
  description = "Nombre del clúster kind creado."
  value       = kind_cluster.noc_tf.name
}

output "kubeconfig_path" {
  description = "Ruta del kubeconfig generado para el clúster."
  value       = kind_cluster.noc_tf.kubeconfig_path
}