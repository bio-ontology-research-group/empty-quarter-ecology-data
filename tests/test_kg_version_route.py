"""The release IRI dereferences without invoking a scientific graph query."""
from pathlib import Path

CONFIG = Path(__file__).resolve().parents[1] / "scripts/release/kg/nginx.candidate.conf"


def test_exact_release_redirect_preserves_public_tls_origin():
    source = CONFIG.read_text()
    block = source.split("location = /kb/v3.0.0/ {", 1)[1].split("}", 1)[0]
    assert "absolute_redirect off;" in block
    assert "add_header Vary Accept always;" in block
    assert "return 303 $kg_version_document;" in block
    assert "proxy_pass" not in block and "DESCRIBE" not in block


def test_negotiation_uses_immutable_targets_and_only_advertises_turtle():
    source = CONFIG.read_text()
    block = source.split("map $http_accept $kg_version_document {", 1)[1].split("}", 1)[0]
    assert "default /downloads/kg/3.0.0/manifest.json;" in block
    assert 'text/turtle' in block
    assert "/downloads/kg/3.0.0/service-description.ttl;" in block
    assert "q=0" in block
    assert "rdf+xml" not in block and "ld+json" not in block


def test_versioned_service_description_has_actual_turtle_mime():
    source = CONFIG.read_text()
    block = source.split("location = /downloads/kg/3.0.0/service-description.ttl {", 1)[1].split("location /kb/", 1)[0]
    assert "alias /release-public/kg/3.0.0/service-description.ttl;" in block
    assert "types { }" in block
    assert "default_type text/turtle;" in block


def test_other_entity_routing_is_unchanged():
    source = CONFIG.read_text()
    block = source.split("    location /kb/ {", 1)[1].split("    location /ontology/", 1)[0]
    assert block == """
        if ($kg_rdf) {
            rewrite ^/kb/(.*)$ /sparql?query=DESCRIBE+%3Chttps://rubalkhali.science/kb/$1%3E last;
        }
        add_header Cache-Control "no-cache, must-revalidate" always;
        try_files /index.html =404;
    }
"""
