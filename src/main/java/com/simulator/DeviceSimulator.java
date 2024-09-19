package com.simulator;

import com.simulator.avro.HealthRecord;

import org.apache.kafka.clients.producer.KafkaProducer;
import org.apache.kafka.clients.producer.ProducerConfig;
import org.apache.kafka.clients.producer.ProducerRecord;
import org.apache.kafka.clients.producer.RecordMetadata;
import org.apache.kafka.common.serialization.StringSerializer;
import io.confluent.kafka.serializers.KafkaAvroSerializer;
import io.confluent.kafka.serializers.AbstractKafkaSchemaSerDeConfig;

import java.util.Properties;
import java.util.Random;
import java.util.concurrent.ExecutionException;
import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.TimeUnit;
import java.time.ZonedDateTime;
import java.time.format.DateTimeFormatter;

import org.json.JSONObject;

public class DeviceSimulator {
    
    //Initialize global variables
    public static final String KAFKA_TOPIC = "health-data-records";
    public static final String BOOTSTRAP_SERVERS = "localhost:29092,localhost:29093,localhost:29094";

    private static String getCurrentTimestamp() {
        ZonedDateTime currentTimestamp = ZonedDateTime.now();
        DateTimeFormatter formatter = DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss");
        String formattedTimestamp = currentTimestamp.format(formatter);
        return formattedTimestamp;
    }
    
    //Develop the function to generate random health monitoring data
    private static JSONObject generateData(String deviceId) {
        // Create a Random object
        Random random = new Random();
        
        // Generate random health records
        int heartRate = random.nextInt(100) + 150;
        double temperature = random.nextDouble() + 37.0;
        int spo2 =  random.nextInt(30) + 70;
        String received_timestamp = getCurrentTimestamp();

        // Create a JSON object
        JSONObject jsonObject = new JSONObject();

        // Put the random numbers into the JSON object
        jsonObject.put("device_id", deviceId);
        jsonObject.put("heart_rate", heartRate);
        jsonObject.put("temperature", temperature);
        jsonObject.put("spo2", spo2);
        jsonObject.put("timestamp", received_timestamp);

        return jsonObject;
    }

    private static KafkaProducer<String, Object> createKafkaProducer() {
        //Initialize Producer Properties object
        Properties props = new Properties();

        //default KafkaProducer config
        props.put(ProducerConfig.BOOTSTRAP_SERVERS_CONFIG, BOOTSTRAP_SERVERS);
        props.put(ProducerConfig.KEY_SERIALIZER_CLASS_CONFIG, StringSerializer.class.getName());
        props.put(ProducerConfig.VALUE_SERIALIZER_CLASS_CONFIG, KafkaAvroSerializer.class.getName());
        props.put(AbstractKafkaSchemaSerDeConfig.SCHEMA_REGISTRY_URL_CONFIG, "http://localhost:8081");

        //High Throughput Props
        props.put(ProducerConfig.ACKS_CONFIG, "all");
        props.put(ProducerConfig.LINGER_MS_CONFIG, "5");
        props.put(ProducerConfig.BATCH_SIZE_CONFIG, "16384");
        // props.put(ProducerConfig.MAX_IN_FLIGHT_REQUESTS_PER_CONNECTION, "1");
       
        return new KafkaProducer<>(props);
    }

    public static void main(String[] args) throws ExecutionException, InterruptedException {        
        // Intialize Producer Object
        KafkaProducer<String, Object> producer = createKafkaProducer();
        System.out.printf("Producer created at: %s\n", getCurrentTimestamp());

        // Set number of concurrent tasks/devices running in parallel
        int num_threads = Integer.valueOf(args[0]);

        // Set frequency intervals to re-send data from each device
        int timeIntervals = 10;

        // Create a thread pool with 10 threads
        ScheduledExecutorService executorService = Executors.newScheduledThreadPool(num_threads);

        // Submit tasks to the executor service
        for (int i = 0; i < num_threads; i++) {
            int threadNumber = i;
            String deviceId = "device_" + (threadNumber + 1);
            executorService.scheduleAtFixedRate(() -> {
                // Generate data
                JSONObject data_generator = generateData(deviceId);
                // Convert JSON to Avro using the generated Avro class
                HealthRecord avroRecord = HealthRecord.newBuilder()
                    .setDeviceId(data_generator.getString("device_id"))
                    .setHeartRate(data_generator.getInt("heart_rate"))
                    .setTemperature(data_generator.getDouble("temperature"))
                    .setSpo2(data_generator.getInt("spo2"))
                    .setTimestamp(data_generator.getString("timestamp"))
                    .build();
                //Create a Producer record
                ProducerRecord<String, Object> record = new ProducerRecord<>(KAFKA_TOPIC, deviceId, avroRecord);
                //Publish record to Producer
                try{
                    RecordMetadata metadata = producer.send(record).get();
                    System.out.printf(
                    "Sent message: record(key=%s, value=%s) metadata(topic=%s, partition=%s, offset=%s)\n",
                    record.key(), record.value(), metadata.topic(), metadata.partition(), metadata.offset()
                );
                } catch (InterruptedException | ExecutionException e) {
                    e.printStackTrace();
                }
            }, 0, timeIntervals, TimeUnit.SECONDS);
        }
        // producer.flush();
        // Add shutdown hook to gracefully close the producer
        Runtime.getRuntime().addShutdownHook(new Thread(() -> {
            System.out.println("Shutting down producer...");
            producer.close();
            executorService.shutdown();
            try {
                if (!executorService.awaitTermination(2, TimeUnit.SECONDS)) {
                    System.out.println("Forcing shutdown...");
                    executorService.shutdownNow();
                }
            } catch (InterruptedException e) {
                executorService.shutdownNow();
            }
            System.out.println("Producer shut down.");
        }));
    }
}