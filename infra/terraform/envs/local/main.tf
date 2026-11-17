provider "kind" {}
provider "helm" {
  kubernetes = {
    host                   = kind_cluster.noc_tf.endpoint
    cluster_ca_certificate = kind_cluster.noc_tf.cluster_ca_certificate
    client_certificate     = kind_cluster.noc_tf.client_certificate
    client_key             = kind_cluster.noc_tf.client_key
  }
}

resource "kind_cluster" "noc_tf" {
  name            = var.cluster_name
  node_image      = var.node_image
  wait_for_ready  = true
  kubeconfig_path = "${path.module}/${var.cluster_name}.kubeconfig"

  kind_config {
    kind        = "Cluster"
    api_version = "kind.x-k8s.io/v1alpha4"

    node {
      role = "control-plane"
    }
    node {
      role = "worker"
    }
    node {
      role = "worker"
    }
  }
}

resource "helm_release" "argocd" {
  name             = "argocd"
  namespace        = "argocd"
  create_namespace = true
  repository       = "https://argoproj.github.io/argo-helm"
  chart            = "argo-cd"
  version          = "10.18.0"
  wait             = true
  timeout          = 600
}