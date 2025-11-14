# Sistema de Rehabilitación con Realidad Virtual y Análisis Biomecánico en Tiempo Real

Este estudio presenta un sistema innovador que combina Realidad Virtual (VR) inmersiva con análisis biomecánico cuantitativo para mejorar la rehabilitación de lesiones comunes en el hombro, como la tendinitis del manguito rotador.

![Demostración del análisis](images/gui_analisis.png)

## 🌟 Características Principales

* **Terapia Inmersiva:** Utiliza un visor **Meta Quest VR** para sumergir a los pacientes en escenarios terapéuticos tipo videojuego.
* **Análisis Biomecánico:** Un algoritmo de visión por computadora en **Python** (usando MediaPipe y OpenCV) analiza grabaciones de video para calcular el **Rango de Movimiento (ROM)** del hombro (Flexión y Abducción).
* **Alta Motivación:** Los pacientes en el estudio piloto reportaron mayor motivación y compromiso en comparación con la fisioterapia tradicional.
* **Gestión de Pacientes:** Incluye una base de datos SQLite para el registro y seguimiento de pacientes.
* **Reportes en PDF:** Genera reportes automáticos de la sesión de terapia.

## 🖥️ Vistas del Sistema

| Registro de Paciente | Menú Principal |
| :---: | :---: |
| ![Registro de paciente](images/gui_registro.jpg) | ![Menú principal](images/gui_principal.jpg) |

## 🛠️ Instalación y Uso

Para ejecutar este proyecto localmente, sigue estos pasos:

1.  **Clona el repositorio:**
    ```bash
    git clone [https://github.com/TU_USUARIO/VR-Rehabilitacion-Hombro.git](https://github.com/TU_USUARIO/VR-Rehabilitacion-Hombro.git)
    cd VR-Rehabilitacion-Hombro
    ```

2.  **(Recomendado) Crea un entorno virtual:**
    ```bash
    python -m venv venv
    source venv/bin/activate  # En Windows usa: venv\Scripts\activate
    ```

3.  **Instala las dependencias:**
    ```bash
    pip install -r requirements.txt
    ```

4.  **Ejecuta la aplicación:**
    ```bash
    python src/proyecto2.py
    ```

## 📄 Publicación y Autores

Este trabajo fue aceptado para su publicación. Para más detalles sobre la metodología y los resultados del estudio piloto, por favor consulta nuestro artículo:

* **[Consulta el artículo aquí](./paper/AbarcaCruzMED287.docx)**

### Autores

* Félix Raúl Abarca Cruz
* Fabian Galindo López
* Ing. Georgina Hernández Santiz
* Ing. Dorian Alberto Ibáñez Nangúelú
* Dr. Christian Roberto Ibáñez Nangúelú
* LFT. Jocelyn Ittai Aceves Guillén
* Dra. Diana Paulina Martínez Cancino
* Dr. José Octavio Vázquez Buenos Aires
* Dr. Norberto Urbina Brito
* Jorge Alberto Rodríguez Ramírez
