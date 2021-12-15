# setup ----
library(dplyr)
library(ggplot2)
library(RColorBrewer)
input_file_path <- "D:\\projets_themes\\others\\marbec_green\\sondage\\consommation_internet_marbec.csv"
output_directory_path <- "D:\\projets_themes\\others\\marbec_green\\sondage"

# data import ----
data <- tibble(read.csv2(file = input_file_path)) %>%
  mutate(length_to = as.numeric(x = length_to))

# data design ----
global_answers <- group_by(.data = data,
                           non_mutualised_online_space) %>%
  summarise(nb = n()) %>%
  arrange(desc(x = non_mutualised_online_space)) %>%
  mutate(prop = nb / sum(nb) * 100,
         ypos = cumsum(x = prop) - 0.5 * prop,
         label = paste0(non_mutualised_online_space,
                        " (",
                        round(x = prop),
                        "%)"))

non_mutualised_online_space_repartition <- data$names 
non_mutualised_online_space_repartition <- non_mutualised_online_space_repartition[non_mutualised_online_space_repartition != ""]
non_mutualised_online_space_repartition <- tibble("non_mutualised_online_space_name" = unlist(lapply(seq_len(length.out = length(x = non_mutualised_online_space_repartition)),
                                                                                                     function(a) {
                                                                                                       if (length(x = unlist(x = strsplit(x = non_mutualised_online_space_repartition[a], split = ", "))) != 1) {
                                                                                                         unlist(x = strsplit(x = non_mutualised_online_space_repartition[a], split = ", "))
                                                                                                       } else {
                                                                                                         non_mutualised_online_space_repartition[a]
                                                                                                       }
                                                                                                     }))) %>%
  group_by(non_mutualised_online_space_name) %>%
  summarise(nb = n()) %>%
  arrange(desc(x = non_mutualised_online_space_name)) %>%
  mutate(prop = nb / sum(nb) * 100,
         ypos = cumsum(x = prop) - 0.5 * prop,
         label = paste0(non_mutualised_online_space_name,
                        " (",
                        round(x = prop),
                        "%)"))

global_length_to <- sum(data$length_to,
                        na.rm = TRUE)

# graphic design ----
global_answers_graph <- ggplot(data = global_answers,
       aes(x ="",
           y = nb,
           fill = label)) +
  geom_bar(stat = "identity",
           width = 1,
           color = "white") +
  coord_polar("y",
              start = 0) +
  theme_void() +
  ggtitle(paste0("Réponses globales au sondage\n(",
                 nrow(x = data),
                 " participants)")) +
  theme(legend.title = element_blank())

ggsave(filename = paste(output_directory_path,
                        "global_answers_graph.jpeg",
                        sep = "\\"),
       plot = global_answers_graph,
       height = 7,
       width = 14,
       units = "cm")

non_mutualised_online_space_repartition_graph <- ggplot(data = non_mutualised_online_space_repartition,
                                                        aes(x ="",
                                                            y = nb,
                                                            fill = label)) +
  geom_bar(stat = "identity",
           width = 1,
           color = "white") +
  coord_polar("y",
              start = 0) +
  theme_void() +
  ggtitle("Résumé des espaces en ligne (non mutualisée) utilisés") +
  theme(legend.title = element_blank())

ggsave(filename = paste(output_directory_path,
                        "non_mutualised_online_space_repartition_graph.jpeg",
                        sep = "\\"),
       plot = non_mutualised_online_space_repartition_graph,
       height = 8,
       width = 16,
       units = "cm")
