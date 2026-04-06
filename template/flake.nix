{
  description = "{{ copier__project_name }}  dev environment";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = { self, nixpkgs, flake-utils, ... }@inputs:
    flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = import nixpkgs {
          inherit system;
        };
      in
      {
        devShells.default = pkgs.mkShell {
          buildInputs = with pkgs; [
            (python3.withPackages (ps: with ps; [
              black
              botocore
              boto3
              bandit
              diagrams
              isort
              mkdocs-material
              mkdocs-mermaid2-plugin
              psycopg2
              pip
            ]))
            awscli2
            argocd
            bashInteractive
            copier
            coreutils
            curl
            entr
            envsubst
            gh
            gnumake
            gnused
            go
            go-task
            graphviz
            jq
            kind
            kubectl
            kubernetes-helm
            kubeseal
            nodejs_22
            eslint
            prettier
            openssh
            opentofu
            pass
            pre-commit
            podman
            podman-compose
            talosctl
            tilt
            yq
          ];
          shellHook = ''
            echo "{{ copier__project_name }} dev environment shell hook"
            export LC_ALL=en_US.UTF-8
            export LANG=en_US.UTF-8
          '';
        };
      }
    );
}
