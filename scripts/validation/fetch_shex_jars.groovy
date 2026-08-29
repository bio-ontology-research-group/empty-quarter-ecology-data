// Run once: `groovy scripts/validation/fetch_shex_jars.groovy`
//
// Resolves Jena 4.10 ShEx + transitive deps via Grape (which uses Ivy and
// honors version conflict resolution), then writes the deconflicted
// classpath to scripts/validation/.shex_classpath for shexvalidate.sh.
//
// We DON'T use a wildcard over the entire ~/.groovy/grapes cache because
// that picks up duplicate-versioned dependencies (commons-codec 1.13 and
// 1.16 from different transitive paths) — the older one ends up first on
// the classpath and Jena 4.10's MurmurHash3.hash128x64() blows up with
// NoSuchMethodError.
//
// Idempotent. Safe to re-run after upgrades.

import groovy.grape.Grape

def jars = Grape.resolve(
    [autoDownload: true, classLoader: new GroovyClassLoader()],
    [group: 'org.apache.jena', module: 'jena-shex',     version: '4.10.0'],
    [group: 'org.apache.jena', module: 'jena-arq',      version: '4.10.0'],
    [group: 'org.slf4j',       module: 'slf4j-simple',  version: '2.0.9']
)

def paths = jars.collect { new File(it).absolutePath }
def out = new File('scripts/validation/.shex_classpath')
out.text = paths.join(File.pathSeparator)

println "Resolved ${paths.size()} JARs."
println "Wrote classpath to ${out.absolutePath}."
