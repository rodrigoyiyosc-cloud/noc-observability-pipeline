provider "kind" {}

resource "kind_cluster" "noc_tf" {
  name            = "noc-tf"
  node_image      = "kindest/node:v1.37.0@sha256:a1ed56cfb0e7b93589bdf97c8cd566405a265939e3620fc4f5de89adff580ae5"
  wait_for_ready  = true
  kubeconfig_path = "${path.module}/noc-tf.kubeconfig"

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