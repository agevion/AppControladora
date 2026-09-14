package com.controladora.movil.net

import android.content.Context
import com.controladora.movil.BuildConfig
import java.security.KeyStore
import java.security.cert.CertificateFactory
import javax.net.ssl.KeyManagerFactory
import javax.net.ssl.SSLContext
import javax.net.ssl.SSLSocketFactory
import javax.net.ssl.TrustManagerFactory
import javax.net.ssl.X509TrustManager

/**
 * Los dos extremos del mTLS.
 *
 * Fijate en que NO se usa el almacen de confianza del sistema: el TrustManager se
 * construye vacio y solo se le mete nuestra CA. Eso es el pinning. Aunque a una CA
 * publica le roben una clave, no puede firmar un certificado que esta app acepte.
 */
object Tls {

    private val p12Password: CharArray get() = BuildConfig.P12_PASSWORD.toCharArray()

    fun build(context: Context): Pair<SSLSocketFactory, X509TrustManager> {
        val keyManagers = run {
            val store = KeyStore.getInstance("PKCS12")
            context.assets.open("client.p12").use { store.load(it, p12Password) }
            KeyManagerFactory.getInstance(KeyManagerFactory.getDefaultAlgorithm())
                .apply { init(store, p12Password) }
                .keyManagers
        }

        val trustManager = run {
            val ca = context.assets.open("ca.crt").use {
                CertificateFactory.getInstance("X.509").generateCertificate(it)
            }
            val store = KeyStore.getInstance(KeyStore.getDefaultType()).apply {
                load(null, null)
                setCertificateEntry("controladora-ca", ca)
            }
            TrustManagerFactory.getInstance(TrustManagerFactory.getDefaultAlgorithm())
                .apply { init(store) }
                .trustManagers
                .filterIsInstance<X509TrustManager>()
                .first()
        }

        val ssl = SSLContext.getInstance("TLS").apply {
            init(keyManagers, arrayOf(trustManager), null)
        }
        return ssl.socketFactory to trustManager
    }
}
