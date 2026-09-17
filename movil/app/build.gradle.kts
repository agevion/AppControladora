import java.util.Properties

plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.kotlin.compose)
}

// El token y el host salen de secrets.properties, que no va al repo y lo genera
// `python scripts/sync_app_secrets.py` desde el lado del PC.
val secrets = Properties().apply {
    val f = rootProject.file("secrets.properties")
    if (f.exists()) f.inputStream().use { load(it) }
}

fun secret(key: String, default: String): String = secrets.getProperty(key) ?: default

// El keystore de release tampoco va al repo (.gitignore ya ignora *.jks); lo crea
// `python scripts/sync_app_secrets.py`. Sin el, assembleRelease saldria SIN FIRMAR
// y el movil rechaza ese APK con "parece que el paquete no es valido", asi que la
// firma se aplica solo si el fichero esta de verdad.
val releaseKeystore = rootProject.file("release.jks")

android {
    namespace = "com.controladora.movil"
    compileSdk {
        version = release(36) {
            minorApiLevel = 1
        }
    }

    defaultConfig {
        applicationId = "com.controladora.movil"
        minSdk = 29
        targetSdk = 36
        versionCode = 1
        versionName = "0.1"

        buildConfigField("String", "DEFAULT_HOST", "\"${secret("host", "")}\"")
        buildConfigField("int", "DEFAULT_PORT", secret("port", "8443"))
        buildConfigField("String", "TOKEN", "\"${secret("token", "")}\"")
        buildConfigField("String", "P12_PASSWORD", "\"${secret("p12_password", "")}\"")
    }

    signingConfigs {
        // Sin secrets.properties no hay password valida para el keystore, asi que
        // la release se queda sin configuracion de firma en vez de intentarlo con
        // una escrita aqui.
        val keystorePassword: String? = secrets.getProperty("release_keystore_password")
        if (releaseKeystore.exists() && keystorePassword != null) {
            create("release") {
                storeFile = releaseKeystore
                storePassword = keystorePassword
                keyAlias = secret("release_key_alias", "controladora")
                keyPassword = secret("release_key_password", keystorePassword)
            }
        }
    }

    buildTypes {
        release {
            optimization {
                enable = false
            }
            signingConfig = signingConfigs.findByName("release")
        }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_11
        targetCompatibility = JavaVersion.VERSION_11
    }
    buildFeatures {
        compose = true
        buildConfig = true
    }
}

dependencies {
    implementation(platform(libs.androidx.compose.bom))
    implementation(libs.androidx.activity.compose)
    implementation(libs.androidx.compose.material3)
    implementation(libs.androidx.compose.material.icons.core)
    implementation(libs.androidx.compose.ui)
    implementation(libs.androidx.compose.ui.graphics)
    implementation(libs.androidx.compose.ui.tooling.preview)
    implementation(libs.androidx.core.ktx)
    implementation(libs.androidx.lifecycle.runtime.ktx)
    implementation(libs.androidx.lifecycle.runtime.compose)
    implementation(libs.androidx.lifecycle.viewmodel.compose)
    implementation(libs.kotlinx.coroutines.android)
    implementation(libs.okhttp)
    implementation(libs.webrtc)

    debugImplementation(libs.androidx.compose.ui.tooling)
}
