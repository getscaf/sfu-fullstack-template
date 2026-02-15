#!/usr/bin/env bash

# Generate base YAML and patch with debugpy support
kubectl kustomize ./k8s/local/ | yq --yaml-output '
  if (.kind == "Service" and .metadata.name == "backend") then
    .spec.ports += [{
      "port": 5678,
      "targetPort": 5678,
      "name": "debug"
    }]
  elif (.kind == "Deployment" and .metadata.name == "backend") then
    .spec.template.spec.containers[0].command = [
      "python", "-m", "debugpy", "--listen", "0.0.0.0:5678", "manage.py", "runserver", "0.0.0.0:8000"
    ] |
    .spec.template.spec.containers[0].ports += [{
      "name": "debug",
      "containerPort": 5678
    }]
  else
    .
  end
'
