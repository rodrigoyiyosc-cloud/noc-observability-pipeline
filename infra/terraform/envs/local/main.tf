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
  # Imágenes por digest (ADR-005). Verificado el 2026-11-19 con
  # docker buildx imagetools inspect y con el imageID de los pods.
  values = [
    yamlencode({
      global = { image = { tag = "v3.6.1@sha256:296e3d74f449b2ce45265613fcb68c18ed7366488360c8ea32f5f2a93d2e5c54" } }
      dex    = { image = { tag = "v2.46.1@sha256:65b72ca0f4b0bf6d4ada84ec21da8851782563404ac7b8f926923d27ceced9ab" } }
      redis  = { image = { tag = "8.6.4-alpine@sha256:2cc044fc5a07c9b701f8f1255a309ae9ad7856e694ac03513bf3648c01e40763" } }
    })
  ]
}